from __future__ import annotations

import os
import sys
from contextlib import ExitStack
from pathlib import Path


def event_image_paths(event):
    """Older manifests only have image_path; newer ones list every photo in image_paths."""
    return event.get("image_paths") or ([event["image_path"]] if event.get("image_path") else [])


def missing_photos(event):
    return len(event_image_paths(event)) < event.get("photos", 1)


class TalkDockDjangoAdapter:
    """The only boundary where benchmark code knows about TalkDock's Django app."""

    MODEL_LABELS = {
        "user": ("accounts", "User"),
        "family": ("families", "FamilyRoom"),
        "membership": ("families", "Membership"),
        "person": ("families", "FamilyPerson"),
        "parent_child": ("families", "ParentChild"),
        "partnership": ("families", "Partnership"),
        "post": ("posts", "Post"),
    }

    def __init__(self, backend_path, database, media_root, settings_module="configs.settings"):
        self.backend_path = Path(backend_path).resolve()
        self.database = Path(database).resolve()
        self.media_root = Path(media_root).resolve()
        self.settings_module = settings_module
        self.models = {}

    def setup(self):
        if not self.backend_path.is_dir():
            raise ValueError(f"backend 폴더를 찾을 수 없습니다: {self.backend_path}")
        sys.path.insert(0, str(self.backend_path))
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", self.settings_module)
        try:
            import django
            from django.apps import apps
            from django.conf import settings
            from django.core.management import call_command
        except ModuleNotFoundError as error:
            raise RuntimeError(
                f"Django가 필요합니다: pip install -r {self.backend_path / 'requirements.txt'}"
            ) from error

        settings.DATABASES["default"]["NAME"] = self.database
        settings.MEDIA_ROOT = self.media_root
        django.setup()
        call_command("migrate", interactive=False, verbosity=0)

        for name, (app_label, model_name) in self.MODEL_LABELS.items():
            model = apps.get_model(app_label, model_name)
            if model is None:
                raise RuntimeError(f"TalkDock 모델을 찾을 수 없습니다: {app_label}.{model_name}")
            self.models[name] = model

    def seed(self, manifest, manifest_path, events, default_password=None, family_id=None):
        """family_id pins the room's primary key so each dataset gets its own Graphiti group."""
        from django.contrib.auth.hashers import make_password
        from django.core.files import File

        User = self.models["user"]
        FamilyRoom = self.models["family"]
        Membership = self.models["membership"]
        Post = self.models["post"]

        family = manifest["family"]
        defaults = manifest.get("credentials", {})
        member_password = default_password or defaults.get("default_password", "Member-Test-2026!")
        room_password = defaults.get("room_password", "Family-Test-2026!")
        members = family["members"]
        tree = family["tree"]
        owner_spec = next(member for member in members if member["username"] == tree["owner_id"])

        users = {}
        for spec in members:
            user, created = User.objects.get_or_create(
                username=spec["username"],
                defaults={"display_name": spec["name"], "gender": spec.get("gender", "unknown")},
            )
            if created:
                user.set_password(spec.get("password", member_password))
                user.save(update_fields=["password"])
            elif user.display_name != spec["name"] or user.gender != spec.get("gender", "unknown"):
                raise ValueError(f"기존 사용자 {user.username}의 이름 또는 gender가 manifest와 다릅니다.")
            users[spec["username"]] = user

        room, _ = FamilyRoom.objects.get_or_create(
            invite_code=family["invite_code"],
            defaults={
                **({"id": family_id} if family_id else {}),
                "name": family["name"],
                "password_hash": make_password(room_password),
                "owner": users[owner_spec["username"]],
            },
        )
        if room.owner_id != users[owner_spec["username"]].pk:
            raise ValueError("기존 가족방 owner가 manifest와 다릅니다.")
        if family_id and room.pk != family_id:
            raise ValueError(f"기존 가족방 ID {room.pk}가 지정한 family_id {family_id}와 다릅니다. "
                             "test DB를 지우고 다시 seed하세요.")

        from django.db import transaction
        from django.db.models import F

        with transaction.atomic():
            people, changed = {}, False
            for spec in members:
                membership = Membership.objects.filter(room=room, user=users[spec["username"]]).first()
                if membership is None:
                    person = self.models["person"].objects.create(room=room, name=spec["name"],
                        gender=spec.get("gender", "unknown"), generation=spec["generation"])
                    membership = Membership.objects.create(room=room, user=users[spec["username"]], person=person)
                    changed = True
                elif membership.person.generation != spec["generation"]:
                    raise ValueError(f"{spec['username']}의 기존 generation이 manifest와 다릅니다.")
                people[spec["username"]] = membership.person
            for link in tree["parents"]:
                _, created = self.models["parent_child"].objects.get_or_create(
                    parent=people[link["parent_id"]], child=people[link["child_id"]])
                changed |= created
            for link in tree["partnerships"]:
                first, second = sorted((people[link["first_id"]].pk, people[link["second_id"]].pk))
                _, created = self.models["partnership"].objects.get_or_create(first_id=first, second_id=second)
                changed |= created
            if changed:
                FamilyRoom.objects.filter(pk=room.pk).update(tree_version=F("tree_version") + 1)

        manifest_root = Path(manifest_path).resolve().parent
        post_ids = {}
        for event in events:
            if missing_photos(event):
                raise ValueError("사진이 없는 manifest는 DB에 넣을 수 없습니다. 이미지 다운로드 후 실행하세요.")
            author = users[event["author_username"]]
            post = Post.objects.filter(room=room, author=author, caption=event["caption"]).first()
            if post is None:
                sources = [manifest_root / path for path in event_image_paths(event)]
                with ExitStack() as stack:
                    files = [File(stack.enter_context(source.open("rb")), name=source.name) for source in sources]
                    if hasattr(Post, "images"):
                        from apps.posts.services import save_post

                        post = save_post(room, author, event["caption"], files)
                    elif len(files) == 1:
                        # The benchmark can also target the historical single-image backend.
                        post = Post.objects.create(room=room, author=author, caption=event["caption"],
                                                   image=files[0])
                    else:
                        raise ValueError("이 backend는 사진이 정확히 한 장인 게시물만 지원합니다.")
                Post.objects.filter(pk=post.pk).update(created_at=event["created_at"])
                post.refresh_from_db()
            post_ids[event["feed_key"]] = post.pk

        return {"family_id": room.pk, "post_ids": post_ids}

    def seed_conversations(self, manifest, post_ids):
        """Add comments and past daily questions; re-running skips rows that already exist."""
        from django.apps import apps
        from django.db import transaction

        Comment = apps.get_model("replies", "Comment")
        VoiceDraft = apps.get_model("replies", "VoiceDraft")
        DailyQuestion = apps.get_model("posts", "DailyQuestion")
        QuestionAnswer = apps.get_model("posts", "QuestionAnswer")
        Post = self.models["post"]
        users = {user.username: user for user in self.models["user"].objects.filter(
            username__in=[member["username"] for member in manifest["family"]["members"]])}
        room = self.models["family"].objects.get(invite_code=manifest["family"]["invite_code"])

        def add_comment(post, spec):
            author = users[spec["author_username"]]
            if Comment.objects.filter(post=post, author=author, text=spec["text"]).exists():
                return
            draft = None
            if spec["source"] == "voice":
                draft = VoiceDraft.objects.create(post=post, author=author, recognized=spec["recognized"],
                                                  converted=spec["text"])
                VoiceDraft.objects.filter(pk=draft.pk).update(created_at=spec["created_at"])
            comment = Comment.objects.create(post=post, author=author, text=spec["text"],
                                             source=spec["source"], draft=draft)
            Comment.objects.filter(pk=comment.pk).update(created_at=spec["created_at"])

        with transaction.atomic():
            for spec in manifest.get("comments", []):
                add_comment(Post.objects.get(pk=post_ids[spec["feed_key"]]), spec)
            for spec in manifest.get("daily_questions", []):
                question = DailyQuestion.objects.filter(room=room, date=spec["date"]).first()
                if question is None:
                    post = Post.objects.create(room=room, author=None, kind="question", caption=spec["title"])
                    Post.objects.filter(pk=post.pk).update(created_at=f"{spec['date']}T00:00:00+09:00")
                    question = DailyQuestion.objects.create(post=post, room=room, date=spec["date"],
                                                            kind=spec["kind"], options=spec["options"])
                for answer in spec["answers"]:
                    row, _ = QuestionAnswer.objects.update_or_create(
                        question=question, author=users[answer["author_username"]],
                        defaults={key: answer[key] for key in ("choice", "other_text", "text", "tiers", "source")},
                    )
                    QuestionAnswer.objects.filter(pk=row.pk).update(
                        created_at=answer["created_at"], updated_at=answer["created_at"])
                for comment in spec["comments"]:
                    add_comment(question.post, comment)
        return {"comments": Comment.objects.filter(post__room=room).count(),
                "daily_questions": DailyQuestion.objects.filter(room=room).count()}

    def close(self):
        """Release DB connections so a worker subprocess can use the SQLite file."""
        try:
            from django.db import connections
        except ModuleNotFoundError:
            return
        connections.close_all()
