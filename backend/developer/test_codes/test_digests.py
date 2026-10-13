import io
import json
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import AccessToken, User
from apps.digests.models import Digest
from apps.digests.services import cutoff, generate_digest
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import Post
from integrations.ai import provider

from .test_posts import sample_image


DAY = date(2026, 10, 1)


def at(day=DAY, hour=21, minute=1):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class DigestAPITests(TestCase):
    def setUp(self):
        test_media = Path(settings.BASE_DIR) / "developer" / "test_media"
        test_media.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=test_media)
        self.addCleanup(temporary.cleanup)
        configured = override_settings(MEDIA_ROOT=temporary.name)
        configured.enable()
        self.addCleanup(configured.disable)

        self.owner = User.objects.create_user(
            username="owner", password="Owner-Passphrase1!",
            display_name="정아", gender=User.Gender.FEMALE,
        )
        self.grandma = User.objects.create_user(
            username="paternal_grandma", password="Relative-Passphrase1!",
            display_name="경자", gender=User.Gender.FEMALE,
        )
        self.outsider = User.objects.create_user(
            username="other_owner", password="Other-Passphrase1!", display_name="외부인"
        )
        self.no_room = User.objects.create_user(
            username="no_room", password="No-Room-Passphrase1!", display_name="미가입자"
        )
        self.room = FamilyRoom.objects.create(
            name="정아네", invite_code="ROOM01", password_hash="hashed", owner=self.owner
        )
        self.other_room = FamilyRoom.objects.create(
            name="다른 가족", invite_code="ROOM02", password_hash="hashed", owner=self.outsider
        )
        Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.OWNER)
        Membership.objects.create(room=self.room, user=self.grandma, slot=Membership.Slot.GRANDMA_FATHER)
        Membership.objects.create(room=self.other_room, user=self.outsider, slot=Membership.Slot.OWNER)
        self.grandma_token = AccessToken.issue(self.grandma)
        self.owner_token = AccessToken.issue(self.owner)
        self.outsider_token = AccessToken.issue(self.outsider)
        self.no_room_token = AccessToken.issue(self.no_room)
        self.post = self.upload("포챔스에서 독개굴 이로치 잡았다~ 간지 ㅁㅌㅊ?", "sample_img_1.png")
        self.set_post_time(self.post, at(hour=20))

    @staticmethod
    def auth(token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def upload(self, caption, image_name):
        response = self.client.post(
            "/api/posts/", {"image": sample_image(image_name), "caption": caption},
            **self.auth(self.owner_token),
        )
        self.assertEqual(response.status_code, 200, response.content)
        return Post.objects.get(pk=response.json()["id"])

    @staticmethod
    def set_post_time(post, created_at):
        Post.objects.filter(pk=post.pk).update(created_at=created_at)
        post.created_at = created_at

    def test_digest_waits_for_cutoff_and_caches_daily_window(self):
        late = self.upload("논문 너무 어려워 ㅠㅠ", "sample_img_2.png")
        self.set_post_time(late, at(hour=22))
        with patch("apps.digests.services.timezone.now", return_value=at(hour=20)):
            self.assertIsNone(generate_digest(self.room, DAY))
        self.assertFalse(Digest.objects.exists())

        with patch("apps.digests.services.timezone.now", return_value=at()), \
             patch.object(provider, "summarize", return_value="정아가 독개굴을 잡았어요.") as summarize:
            first = generate_digest(self.room, DAY)
            second = generate_digest(self.room, DAY)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.status, "ready")
        self.assertEqual(first.window_start, cutoff(self.room, DAY - timedelta(days=1)))
        self.assertEqual(first.window_end, cutoff(self.room, DAY))
        self.assertEqual(list(first.posts.all()), [self.post])
        summarize.assert_called_once()

        with patch("apps.digests.services.timezone.now", return_value=at(day=date(2026, 10, 2))), \
             patch.object(provider, "summarize", return_value="정아가 논문 때문에 힘들어해요."):
            next_day = generate_digest(self.room, date(2026, 10, 2))
        self.assertEqual(list(next_day.posts.all()), [late])
        self.assertEqual(next_day.window_start, first.window_end)
        print("Digest cutoff, daily window, and cache test pass", flush=True)

    def test_empty_window_reopens_only_after_later_cutoff(self):
        self.set_post_time(self.post, at(hour=22))
        with patch("apps.digests.services.timezone.now", return_value=at()), \
             patch.object(provider, "summarize") as summarize:
            empty = generate_digest(self.room, DAY)
        self.assertEqual(empty.status, "empty")
        summarize.assert_not_called()
        original_start = empty.window_start

        self.room.digest_time = time(23, 30)
        self.room.save(update_fields=["digest_time"])
        with patch("apps.digests.services.timezone.now", return_value=at(hour=23)):
            self.assertIsNone(generate_digest(self.room, DAY))
        with patch("apps.digests.services.timezone.now", return_value=at(hour=23, minute=31)), \
             patch.object(provider, "summarize", return_value="정아가 새 소식을 올렸어요.") as summarize:
            refreshed = generate_digest(self.room, DAY)
            generate_digest(self.room, DAY)
        self.assertEqual(refreshed.pk, empty.pk)
        self.assertEqual(refreshed.status, "ready")
        self.assertEqual(refreshed.window_start, original_start)
        self.assertEqual(refreshed.window_end, cutoff(self.room, DAY))
        self.assertEqual(list(refreshed.posts.all()), [self.post])
        summarize.assert_called_once()
        print("Digest empty window extension test pass", flush=True)

    def test_completed_digest_keeps_its_original_window(self):
        with patch("apps.digests.services.timezone.now", return_value=at()), \
             patch.object(provider, "summarize", return_value="이미 준비된 요약"):
            original = generate_digest(self.room, DAY)
        original_end = original.window_end
        self.room.digest_time = time(23, 30)
        self.room.save(update_fields=["digest_time"])
        with patch("apps.digests.services.timezone.now", return_value=at(hour=23, minute=31)), \
             patch.object(provider, "summarize") as summarize:
            unchanged = generate_digest(self.room, DAY)
        self.assertEqual(unchanged.status, "ready")
        self.assertEqual(unchanged.text, "이미 준비된 요약")
        self.assertEqual(unchanged.window_end, original_end)
        summarize.assert_not_called()
        print("Completed digest window preservation test pass", flush=True)

    def test_failed_digest_retries_only_on_post_and_keeps_window(self):
        with patch("apps.digests.services.timezone.now", return_value=at()), \
             patch.object(provider, "summarize", side_effect=provider.AIUnavailable("offline")):
            first = self.client.get(f"/api/digests/?date={DAY}", **self.auth(self.grandma_token))
        self.assertEqual(first.json()["status"], "failed")
        original_end = Digest.objects.get(room=self.room, date=DAY).window_end
        self.room.digest_time = time(22)
        self.room.save(update_fields=["digest_time"])
        with patch("apps.digests.services.timezone.now", return_value=at(hour=22, minute=1)), \
             patch.object(provider, "summarize", return_value="다시 준비된 가족 요약") as summarize:
            cached = self.client.get(f"/api/digests/?date={DAY}", **self.auth(self.grandma_token))
            summarize.assert_not_called()
            retried = self.client.post(
                "/api/digests/", json.dumps({"date": DAY.isoformat()}),
                content_type="application/json", **self.auth(self.grandma_token),
            )
        self.assertEqual(cached.json()["status"], "failed")
        self.assertEqual(retried.json()["status"], "ready")
        self.assertEqual(retried.json()["text"], "다시 준비된 가족 요약")
        self.assertEqual(Digest.objects.get(room=self.room, date=DAY).window_end, original_end)
        summarize.assert_called_once()
        print("Digest failure and explicit retry test pass", flush=True)

    def test_in_progress_digest_waits_and_stale_work_retries(self):
        digest = Digest.objects.create(room=self.room, date=DAY, status="processing")
        with patch("apps.digests.services.timezone.now", return_value=at()), \
             patch.object(provider, "summarize", return_value="새 요약") as summarize:
            self.assertEqual(generate_digest(self.room, DAY).status, "processing")
            summarize.assert_not_called()
            Digest.objects.filter(pk=digest.pk).update(updated_at=at() - timedelta(minutes=3))
            self.assertEqual(generate_digest(self.room, DAY).status, "ready")
            summarize.assert_called_once()
        print("Digest processing lease test pass", flush=True)

    def test_digest_api_history_room_isolation_and_bad_dates(self):
        late = self.upload("논문 너무 어려워 ㅠㅠ", "sample_img_2.png")
        self.set_post_time(late, at(hour=22))
        with patch("apps.digests.services.timezone.now", return_value=at()), \
             patch.object(provider, "summarize", return_value="정아가 독개굴을 잡았어요."):
            ready = self.client.get(f"/api/digests/?date={DAY}", **self.auth(self.grandma_token))
            other = self.client.get(f"/api/digests/?date={DAY}", **self.auth(self.outsider_token))
            history = self.client.get("/api/digests/history/", **self.auth(self.grandma_token))
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ready")
        self.assertEqual(ready.json()["digest_time"], "21:00")
        self.assertEqual([post["id"] for post in ready.json()["posts"]], [self.post.pk])
        self.assertEqual(ready.json()["posts"][0]["relationship"], "손녀")
        self.assertEqual(other.json()["status"], "empty")
        self.assertEqual(other.json()["posts"], [])
        self.assertIn(DAY.isoformat(), history.json()["dates"])
        self.assertIn((DAY + timedelta(days=1)).isoformat(), history.json()["dates"])
        self.assertEqual(self.client.get("/api/digests/").status_code, 401)
        self.assertEqual(self.client.get(
            "/api/digests/history/", **self.auth(self.no_room_token)
        ).status_code, 403)
        self.assertEqual(self.client.get(
            "/api/digests/?date=invalid", **self.auth(self.grandma_token)
        ).status_code, 400)
        self.assertEqual(self.client.get(
            "/api/digests/?date=0001-01-01", **self.auth(self.grandma_token)
        ).status_code, 400)
        self.assertEqual(self.client.post(
            "/api/digests/", json.dumps({"date": 42}), content_type="application/json",
            **self.auth(self.grandma_token),
        ).status_code, 400)
        self.assertEqual(self.client.post(
            "/api/digests/", json.dumps({"date": 0}), content_type="application/json",
            **self.auth(self.grandma_token),
        ).status_code, 400)
        print("Digest API, history, and room isolation test pass", flush=True)

    def test_scheduler_once_is_repeatable(self):
        with patch("apps.digests.services.timezone.now", return_value=at()), \
             patch.object(provider, "summarize", return_value="오늘의 소식") as summarize:
            call_command("run_digest_scheduler", once=True, stdout=io.StringIO())
            call_command("run_digest_scheduler", once=True, stdout=io.StringIO())
        self.assertEqual(Digest.objects.get(room=self.room, date=DAY).status, "ready")
        summarize.assert_called_once()
        print("Digest scheduler repeatability test pass", flush=True)

    def test_ai_summary_receives_post_text_and_image(self):
        with patch.object(provider, "generate", return_value="가족의 하루") as generate:
            self.assertEqual(provider.summarize([self.post]), "가족의 하루")
        self.assertIn("하루 요약", generate.call_args.args[0])
        self.assertEqual(json.loads(generate.call_args.args[1]), [
            {"작성자": "정아", "원문": self.post.caption}
        ])
        self.assertEqual(generate.call_args.args[2], [self.post.image])
        print("Digest AI input test pass", flush=True)
