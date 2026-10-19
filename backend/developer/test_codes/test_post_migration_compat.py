"""Upgrade either independently deployed posts feature without rewriting its history."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class PostMigrationCompatibilityTests(TransactionTestCase):
    def test_upgrades_from_both_feature_histories_preserve_existing_data(self):
        final_targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(final_targets))
        scenarios = [
            ("photos", [("posts", "0003_postphoto")]),
            ("summary", [("posts", "0003_adaptedmessage_prompt_version")]),
            ("both", [("posts", "0003_postphoto"), ("posts", "0003_adaptedmessage_prompt_version")]),
            ("description", [("posts", "0003_post_description")]),
            ("all", [("posts", "0003_post_description"), ("posts", "0004_merge_post_photos_summary_cache")]),
        ]
        for index, (name, targets) in enumerate(scenarios):
            with self.subTest(starting_schema=name):
                MigrationExecutor(connection).migrate([("posts", "0002_adaptedmessage")])
                executor = MigrationExecutor(connection)
                executor.migrate(targets)
                apps = executor.loader.project_state(targets).apps
                owner = apps.get_model("accounts", "User").objects.create(
                    username=f"migration-owner-{index}", display_name="가족")
                room = apps.get_model("families", "FamilyRoom").objects.create(
                    owner_id=owner.pk, name="마이그레이션 가족", invite_code=f"MIG{index}", password_hash="unused")
                post_data = dict(room_id=room.pk, author_id=owner.pk, caption="기존 소식", image="existing.jpg")
                if name in {"description", "all"}:
                    post_data["description"] = "기존에 생성된 상세 설명"
                post = apps.get_model("posts", "Post").objects.create(**post_data)
                message_data = dict(post_id=post.pk, viewer_id=owner.pk, text="기존 설명", status="ready")
                if name in {"summary", "both", "all"}:
                    message_data["prompt_version"] = "previous-policy"
                message = apps.get_model("posts", "AdaptedMessage").objects.create(**message_data)
                if name in {"photos", "both", "all"}:
                    apps.get_model("posts", "PostPhoto").objects.create(
                        post_id=post.pk, image="extra.jpg", position=1)
                executor = MigrationExecutor(connection)
                executor.migrate(final_targets)
                merged = executor.loader.project_state(final_targets).apps
                self.assertEqual(merged.get_model("posts", "Post").objects.get(pk=post.pk).caption, "기존 소식")
                saved = merged.get_model("posts", "AdaptedMessage").objects.get(pk=message.pk)
                self.assertEqual((saved.text, saved.status), ("기존 설명", "ready"))
                self.assertEqual(merged.get_model("posts", "Post").objects.get(pk=post.pk).description,
                                 "기존에 생성된 상세 설명" if name in {"description", "all"} else "")
                self.assertEqual(saved.prompt_version, "previous-policy" if name in {"summary", "both", "all"} else "")
                photos = merged.get_model("posts", "PostPhoto").objects.filter(post_id=post.pk)
                self.assertEqual(list(photos.values_list("image", flat=True)), ["extra.jpg"] if name in {"photos", "both", "all"} else [])
                self.assertEqual(executor.loader.graph.leaf_nodes("posts"),
                    [("posts", "0005_merge_description_photos_summary")])
