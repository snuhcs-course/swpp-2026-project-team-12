"""Upgrade real legacy rows and read their unchanged files through the AI boundary."""

import base64
import tempfile
from pathlib import Path

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings

from apps.posts.models import Post
from integrations.ai.feed_description import _description_content


class PostImagesMigrationTests(TransactionTestCase):
    previous = [("posts", "0005_merge_description_photos_summary")]

    def setUp(self):
        self.latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(self.latest))
        executor = MigrationExecutor(connection)
        executor.migrate(self.previous)
        state_targets = [target for target in self.latest if target[0] != "posts"] + self.previous
        self.old_apps = executor.loader.project_state(state_targets).apps
        user = self.old_apps.get_model("accounts", "User").objects.create(username="images-migration", display_name="정아")
        room = self.old_apps.get_model("families", "FamilyRoom").objects.create(
            owner_id=user.pk, name="사진 가족", invite_code="IMGMIG", password_hash="unused")
        self.post_args = {"room_id": room.pk, "author_id": user.pk}
        self.user_id = user.pk

    def test_upgrade_preserves_files_order_post_identity_and_cached_descriptions(self):
        LegacyPost = self.old_apps.get_model("posts", "Post")
        LegacyPhoto = self.old_apps.get_model("posts", "PostPhoto")
        post = LegacyPost.objects.create(**self.post_args, caption="네 장의 소식", image="legacy/cover.jpg",
                                         description="이미 Graphiti에 보낸 상세 기록")
        # Insert out of order with gaps: the old ordering, not row IDs, must win.
        for position, name in [(9, "fourth"), (2, "second"), (5, "third")]:
            LegacyPhoto.objects.create(post_id=post.pk, image=f"legacy/{name}.jpg", position=position)
        message = self.old_apps.get_model("posts", "AdaptedMessage").objects.create(
            post_id=post.pk, viewer_id=self.user_id, text="캐시된 요약", status="ready", prompt_version="unchanged")
        comment = self.old_apps.get_model("replies", "Comment").objects.create(
            post_id=post.pk, author_id=self.user_id, text="기존 댓글", source="text")
        expected_paths = [f"legacy/{name}.jpg" for name in ("cover", "second", "third", "fourth")]
        expected_bytes = [b"first-photo", b"second-photo", b"third-photo", b"fourth-photo"]
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            for name, content in zip(expected_paths, expected_bytes):
                path = Path(folder) / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(content)
            MigrationExecutor(connection).migrate(self.latest)
            saved = Post.objects.get(pk=post.pk)
            self.assertEqual(saved.images, expected_paths)
            self.assertEqual((saved.room_id, saved.author_id, saved.created_at, saved.caption, saved.description),
                             (post.room_id, post.author_id, post.created_at, post.caption, post.description))
            self.assertEqual([photo.name for photo in saved.photo_files()], expected_paths)
            # This is the actual input used before Graphiti construction; no external calls.
            content = _description_content(saved)
            self.assertEqual([base64.b64decode(item["image_url"].split(",", 1)[1]) for item in content[1:]],
                             expected_bytes)
            self.assertEqual({path.relative_to(folder).as_posix(): path.read_bytes()
                              for path in Path(folder).rglob("*.jpg")}, dict(zip(expected_paths, expected_bytes)))
        self.assertEqual(saved.messages.get(pk=message.pk).text, "캐시된 요약")
        self.assertEqual(saved.messages.get(pk=message.pk).prompt_version, "unchanged")
        self.assertEqual(saved.comments.get(pk=comment.pk).text, "기존 댓글")
        self.assertNotIn("posts_postphoto", connection.introspection.table_names())

    def test_text_single_and_attachment_only_posts_survive_round_trip(self):
        LegacyPost = self.old_apps.get_model("posts", "Post")
        LegacyPhoto = self.old_apps.get_model("posts", "PostPhoto")
        text = LegacyPost.objects.create(**self.post_args, caption="글만", image="")
        single = LegacyPost.objects.create(**self.post_args, caption="한 장", image="single.jpg")
        attachments = LegacyPost.objects.create(**self.post_args, caption="첨부만", image="")
        LegacyPhoto.objects.create(post_id=attachments.pk, image="only-extra.jpg", position=3)
        expected = {text.pk: [], single.pk: ["single.jpg"], attachments.pk: ["only-extra.jpg"]}
        MigrationExecutor(connection).migrate(self.latest)
        self.assertEqual(dict(Post.objects.values_list("pk", "images")), expected)
        executor = MigrationExecutor(connection)
        executor.migrate(self.previous)
        apps = executor.loader.project_state(self.previous).apps
        restored = apps.get_model("posts", "Post").objects.get(pk=single.pk)
        self.assertEqual(restored.image.name, "single.jpg")
        MigrationExecutor(connection).migrate(self.latest)
        self.assertEqual(dict(Post.objects.values_list("pk", "images")), expected)
