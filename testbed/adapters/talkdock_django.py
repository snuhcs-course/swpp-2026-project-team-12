from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def build_post_qa_input(post, event, relation, viewer, current_time):
    """Mirror integrations.ai.provider.ask without hiding retrieval metadata."""
    return json.dumps(
        {
            "작성자": post.author.display_name,
            "관계": relation,
            "원문": post.caption,
            "게시시각": post.created_at.isoformat(),
            "질문": event["evaluation_question"],
            "질문자": viewer["name"],
            "이전대화": event.get("prior_dialogue", []),
            "현재시각": current_time.isoformat(),
        },
        ensure_ascii=False,
    )


class TalkDockDjangoAdapter:
    """The only boundary where benchmark code knows about TalkDock's Django app."""

    MODEL_LABELS = {
        "user": ("accounts", "User"),
        "family": ("families", "FamilyRoom"),
        "membership": ("families", "Membership"),
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

    def seed(self, manifest, manifest_path, events, default_password=None):
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
        owner_spec = next(member for member in members if member["slot"] == "owner")

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
                "name": family["name"],
                "password_hash": make_password(room_password),
                "owner": users[owner_spec["username"]],
            },
        )
        if room.owner_id != users[owner_spec["username"]].pk:
            raise ValueError("기존 가족방 owner가 manifest와 다릅니다.")

        for spec in members:
            membership, created = Membership.objects.get_or_create(
                room=room,
                user=users[spec["username"]],
                defaults={"slot": spec["slot"]},
            )
            if not created and membership.slot != spec["slot"]:
                raise ValueError(f"{spec['username']}의 기존 slot이 manifest와 다릅니다.")

        manifest_root = Path(manifest_path).resolve().parent
        post_ids = {}
        for event in events:
            if not event.get("image_path"):
                raise ValueError("사진이 없는 manifest는 DB에 넣을 수 없습니다. 이미지 다운로드 후 실행하세요.")
            author = users[event["author_username"]]
            post = Post.objects.filter(room=room, author=author, caption=event["caption"]).first()
            if post is None:
                source = manifest_root / event["image_path"]
                with source.open("rb") as handle:
                    post = Post.objects.create(
                        room=room,
                        author=author,
                        caption=event["caption"],
                        image=File(handle, name=source.name),
                    )
                Post.objects.filter(pk=post.pk).update(created_at=event["created_at"])
                post.refresh_from_db()
            post_ids[event["feed_key"]] = post.pk

        return {"family_id": room.pk, "post_ids": post_ids}

    def close(self):
        """Release DB connections so a worker subprocess can use the SQLite file."""
        try:
            from django.db import connections
        except ModuleNotFoundError:
            return
        connections.close_all()

    def evaluate(self, manifest, database_state, on_case_done=None):
        """Run the backend's post QA path while preserving retrieval evidence."""
        from integrations.ai_workers.searching_workers import run_search
        from django.utils import timezone

        Post = self.models["post"]
        family_id = database_state["family_id"]
        post_ids = database_state["post_ids"]
        members = manifest["family"]["members"]
        relationships = manifest["family"]["relationship_matrix"]
        probes = [event for event in manifest["events"] if event["kind"] == "probe"]
        cases = []

        for probe_index, event in enumerate(probes, 1):
            post = Post.objects.select_related("author").get(pk=post_ids[event["feed_key"]])
            if hasattr(post, "photo_files"):
                images = post.photo_files()
            else:
                images = [post.image] if post.image else []
            for viewer_index, viewer in enumerate(members, 1):
                relation = relationships[viewer["username"]][event["author_username"]]
                question = event["evaluation_question"]
                prior_dialogue = event.get("prior_dialogue", [])
                content = build_post_qa_input(post, event, relation, viewer, timezone.now())
                result = run_search("post_qa", family_id, content, images=images)
                cases.append({
                    "feed_key": event["feed_key"],
                    "thread_id": event["thread_id"],
                    "viewer_username": viewer["username"],
                    "viewer_name": viewer["name"],
                    "author_username": event["author_username"],
                    "expected_relationship": relation,
                    "question": question,
                    "prior_dialogue": prior_dialogue,
                    "answer": result["text"],
                    "query": result.get("query"),
                    "queries": result.get("queries", []),
                    "memories": result.get("memories", []),
                })
                if on_case_done:
                    on_case_done(
                        probe_index,
                        len(probes),
                        viewer_index,
                        len(members),
                        event["feed_key"],
                        viewer["name"],
                    )
        return cases
