import base64
import io
import json
import os
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom
from apps.posts.models import AdaptedMessage, Post
from integrations.ai import flow, provider, post_flow
from integrations.ai_workers import graphiti_client, searching_workers

from .family_fixtures import add_member, link_parent, sample_family


SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"
TEST_MEDIA_DIR = Path(__file__).resolve().parents[1] / "test_media"


def sample_image(name="sample_img_1.png"):
    return SimpleUploadedFile(name, (SAMPLES_DIR / name).read_bytes(), content_type="image/png")


class PostAPITests(TestCase):
    def setUp(self):
        pool = searching_workers.SearchPool(1)
        self.enterContext(patch.object(searching_workers, "SEARCH_POOL", pool))
        self.enterContext(patch.object(graphiti_client, "close_graphiti", new=AsyncMock()))
        self.addCleanup(pool.shutdown)
        with patch.object(graphiti_client, "create_graphiti",
                          return_value=SimpleNamespace(search=AsyncMock(return_value=[]))):
            pool.start()
        media_settings = override_settings(MEDIA_ROOT=TEST_MEDIA_DIR)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

        self.owner = User.objects.create_user(
            username="owner", password="Owner-Passphrase1!", display_name="정아", gender=User.Gender.FEMALE
        )
        self.relative = User.objects.create_user(
            username="relative", password="Relative-Passphrase1!", display_name="준호", gender=User.Gender.MALE
        )
        self.outsider = User.objects.create_user(
            username="outsider", password="Outsider-Passphrase1!", display_name="타인"
        )
        self.room = FamilyRoom.objects.create(
            name="정아네", invite_code="ROOM01", password_hash="hashed", owner=self.owner
        )
        self.other_room = FamilyRoom.objects.create(
            name="다른 가족", invite_code="ROOM02", password_hash="hashed", owner=self.outsider
        )
        add_member(self.room, self.owner)
        add_member(self.room, self.relative, -1)
        link_parent(self.room, self.room.owner, self.relative)
        add_member(self.other_room, self.outsider)
        self.owner_token = AccessToken.issue(self.owner)
        self.relative_token = AccessToken.issue(self.relative)
        self.outsider_token = AccessToken.issue(self.outsider)

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def upload(self, caption="", image=None):
        return self.client.post(
            "/api/posts/",
            {"image": image if image is not None else sample_image(),
             "caption": caption},
            **self.auth(self.owner_token),
        )

    def test_feed_returns_latest_100_in_stable_newest_first_order(self):
        posts = Post.objects.bulk_create([
            Post(room=self.room, author=self.owner, caption=f"소식 {index}") for index in range(102)
        ])
        # Equal timestamps still have a stable newest-first ID order.
        Post.objects.filter(pk__in=[posts[-1].pk, posts[-2].pk]).update(
            created_at=timezone.now() + timedelta(days=1)
        )
        Post.objects.create(room=self.other_room, author=self.outsider, caption="다른 가족 소식")
        response = self.client.get("/api/posts/", **self.auth(self.relative_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["posts"]],
                         [post.pk for post in reversed(posts)][:100])
        self.assertTrue(all(item["comment_count"] == 0 for item in response.json()["posts"]))

    def test_grandma_post_summaries(self):
        use_mock = os.getenv("MOCK_AI_TESTS") == "1"
        if not use_mock and not settings.OPENAI_API_KEY:
            self.skipTest("Set OPENAI_API_KEY for live summaries, or MOCK_AI_TESTS=1 for fixed responses")

        family = sample_family(self.room, self.owner, son=self.relative)
        grandma_token = AccessToken.issue(family["paternal_grandma"])
        self.assertEqual({user.display_name for user in family.values()},
                         {"정아", "경자", "선희", "병호", "지현", "준호", "수아"})

        mock_responses = (
            "손녀 정아가 포챔스에서 색이 다른 독개굴을 잡았다고 해요. 멋진지 가족에게 물어봤어요.",
            "손녀 정아가 논문이 너무 어렵다고 해요. 가족에게 힘든 마음을 전했어요.",
        )
        generation = patch.object(provider, "adapt", side_effect=mock_responses) if use_mock else nullcontext()
        with generation:
            for image_name, caption in (
                ("sample_img_1.png", "포챔스에서 독개굴 이로치 잡았다~ 간지 ㅁㅌㅊ?"),
                ("sample_img_2.png", "논문 너무 어려워 ㅠㅠ"),
            ):
                uploaded = self.upload(caption, sample_image(image_name))
                self.assertEqual(uploaded.status_code, 200)
                post_id = uploaded.json()["id"]
                self.assertEqual(Post.objects.get(pk=post_id).caption, caption)
                path = f"/api/posts/{post_id}/message/"
                result = self.client.get(path, **self.auth(grandma_token))
                print(result.json()["text"], flush=True)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["status"], "ready", result.json())
                self.assertTrue(result.json()["text"].strip())
                self.assertEqual(
                    AdaptedMessage.objects.get(post_id=post_id).viewer.display_name, "경자"
                )
                with patch.object(provider, "adapt") as adapt:
                    cached = self.client.get(path, **self.auth(grandma_token))
                    adapt.assert_not_called()
                self.assertEqual(cached.json(), result.json())

        feed = self.client.get("/api/posts/", **self.auth(grandma_token))
        self.assertEqual([post["relationship"] for post in feed.json()["posts"]], ["손녀", "손녀"])
        print(f"Grandma {'mock' if use_mock else 'live'} AI summaries test pass", flush=True)

    def test_live_family_member_post_summaries(self):
        if os.getenv("RUN_LIVE_SUMMARY_MATRIX") != "1":
            self.skipTest("Set RUN_LIVE_SUMMARY_MATRIX=1 to compare live summaries for every viewer")
        if not settings.OPENAI_API_KEY:
            self.skipTest("Set OPENAI_API_KEY to run live summaries")

        viewers = [
            (self.owner, self.owner_token, "나"),
            (self.relative, self.relative_token, "어머니"),
        ]
        family = sample_family(self.room, self.owner, son=self.relative)
        for key, expected_relation in (("paternal_grandma", "손녀"), ("maternal_grandma", "손녀"),
                                       ("father", "딸"), ("mother", "딸"), ("daughter", "어머니")):
            viewer = family[key]
            viewers.append((viewer, AccessToken.issue(viewer), expected_relation))

        uploaded = self.upload(
            "포챔스에서 독개굴 이로치 잡았다~ 간지 ㅁㅌㅊ?",
            sample_image("sample_img_1.png"),
        )
        self.assertEqual(uploaded.status_code, 200)
        post_id = uploaded.json()["id"]
        path = f"/api/posts/{post_id}/message/"

        for viewer, token, expected_relation in viewers:
            with self.subTest(viewer=viewer.display_name, relation=expected_relation):
                feed = self.client.get("/api/posts/", **self.auth(token))
                self.assertEqual(feed.json()["posts"][0]["relationship"], expected_relation)
                result = self.client.get(path, **self.auth(token))
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["status"], "ready", result.json())
                summary = result.json()["text"].strip()
                self.assertTrue(summary)
                print(
                    f"[{viewer.display_name} 관점 / 작성자 관계: {expected_relation}] {summary}",
                    flush=True,
                )

        self.assertEqual(AdaptedMessage.objects.filter(post_id=post_id).count(), len(viewers))

    def test_upload_converts_sample_and_returns_feed_and_detail(self):
        response = self.upload("오늘 산책했어요", sample_image("sample_img_1.png"))
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get(pk=response.json()["id"])
        self.assertEqual(post.room, self.room)
        self.assertEqual(post.author, self.owner)
        self.assertEqual(post.caption, "오늘 산책했어요")
        try:
            with Image.open(post.image) as stored:
                self.assertEqual(stored.format, "JPEG")
                self.assertEqual(stored.size, (1345, 622))
        finally:
            post.image.close()

        feed = self.client.get("/api/posts/", **self.auth(self.relative_token))
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(len(feed.json()["posts"]), 1)
        self.assertEqual(feed.json()["posts"][0]["relationship"], "어머니")
        self.assertEqual(feed.json()["posts"][0]["comment_count"], 0)
        detail = self.client.get(f"/api/posts/{post.pk}/", **self.auth(self.relative_token))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["comments"], [])
        print("Post upload/feed/detail test pass", flush=True)

    def test_upload_resizes_large_sample(self):
        with Image.open(SAMPLES_DIR / "sample_img_2.png") as source:
            enlarged = source.resize((1800, 1178))
            output = io.BytesIO()
            enlarged.save(output, format="PNG")
        response = self.upload(image=SimpleUploadedFile(
            "enlarged_sample_img_2.png", output.getvalue(), content_type="image/png"
        ))
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get(pk=response.json()["id"])
        try:
            with Image.open(post.image) as stored:
                self.assertEqual(stored.format, "JPEG")
                self.assertLessEqual(max(stored.size), 1600)
        finally:
            post.image.close()
        print("Post image resize test pass", flush=True)

    def test_photo_requires_membership_and_stays_within_room(self):
        post_id = self.upload(image=sample_image("sample_img_2.png")).json()["id"]
        image_path = f"/api/posts/{post_id}/image/"
        self.assertEqual(self.client.get(image_path).status_code, 401)
        self.assertEqual(self.client.get("/api/posts/", **self.auth(self.outsider_token)).json()["posts"], [])
        self.assertEqual(self.client.get(f"/api/posts/{post_id}/", **self.auth(self.outsider_token)).status_code, 404)
        self.assertEqual(self.client.get(image_path, **self.auth(self.outsider_token)).status_code, 404)
        response = self.client.get(image_path, **self.auth(self.relative_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, max-age=300")
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\xff\xd8"))
        response.close()
        print("Post room privacy test pass", flush=True)

    def test_invalid_uploads_do_not_create_posts(self):
        self.assertEqual(self.client.post("/api/posts/", {}, **self.auth(self.owner_token)).status_code, 400)
        self.assertEqual(self.upload(image=SimpleUploadedFile("bad.jpg", b"not a photo")).status_code, 400)
        self.assertEqual(self.upload(caption="x" * 2001).status_code, 400)
        self.assertEqual(self.upload(image=SimpleUploadedFile("huge.jpg", b"x" * (10 * 1024 * 1024 + 1))).status_code, 400)
        self.assertEqual(Post.objects.count(), 0)
        print("Post upload validation test pass", flush=True)

    @override_settings(PUBLIC_ORIGIN="https://team-test.trycloudflare.com")
    def test_image_url_uses_configured_public_origin(self):
        post_id = self.upload().json()["id"]
        feed = self.client.get("/api/posts/", **self.auth(self.relative_token))
        self.assertEqual(
            feed.json()["posts"][0]["image_url"],
            f"https://team-test.trycloudflare.com/api/posts/{post_id}/image/",
        )
        print("Post public image URL test pass", flush=True)

    def test_message_is_private_and_cached_per_viewer(self):
        post_id = self.upload(caption="오늘 산책했어요").json()["id"]
        path = f"/api/posts/{post_id}/message/"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, **self.auth(self.outsider_token)).status_code, 404)
        self.assertEqual(AdaptedMessage.objects.count(), 0)

        with patch.object(provider, "adapt", side_effect=["정아의 산책 소식이에요.", "오늘 산책했어요."]) as adapt:
            first = self.client.get(path, **self.auth(self.relative_token))
            again = self.client.get(path, **self.auth(self.relative_token))
            other = self.client.get(path, **self.auth(self.owner_token))
        self.assertEqual(first.json(), {"text": "정아의 산책 소식이에요.", "status": "ready"})
        self.assertEqual(again.json(), first.json())
        self.assertEqual(other.json()["status"], "ready")
        self.assertEqual(adapt.call_count, 2)
        self.assertEqual(adapt.call_args_list[0].args[1], "어머니")
        self.assertEqual(AdaptedMessage.objects.count(), 2)
        print("Post AI message cache and privacy test pass", flush=True)

    @override_settings(OPENAI_API_KEY="")
    def test_message_failure_requires_explicit_retry(self):
        post_id = self.upload().json()["id"]
        path = f"/api/posts/{post_id}/message/"
        with patch("urllib.request.urlopen") as request:
            first = self.client.get(path, **self.auth(self.relative_token))
            request.assert_not_called()
        self.assertEqual(first.json(), {"text": "", "status": "failed"})

        with patch.object(provider, "adapt", return_value="다시 준비된 소식이에요.") as adapt:
            self.assertEqual(self.client.get(path, **self.auth(self.relative_token)).json()["status"], "failed")
            adapt.assert_not_called()
            retry = self.client.post(path, **self.auth(self.relative_token))
            self.assertEqual(retry.json(), {"text": "다시 준비된 소식이에요.", "status": "ready"})
            self.client.post(path, **self.auth(self.relative_token))
            adapt.assert_called_once()
        print("Post AI message retry test pass", flush=True)

    def test_message_processing_is_claimed_once_and_stale_work_retries(self):
        post_id = self.upload().json()["id"]
        path = f"/api/posts/{post_id}/message/"
        message = AdaptedMessage.objects.create(
            post_id=post_id, viewer=self.relative, status="processing"
        )
        with patch.object(provider, "adapt", return_value="다시 생성된 소식이에요.") as adapt:
            current = self.client.get(path, **self.auth(self.relative_token))
            self.assertEqual(current.json()["status"], "processing")
            adapt.assert_not_called()
            AdaptedMessage.objects.filter(pk=message.pk).update(
                updated_at=timezone.now() - timedelta(minutes=3)
            )
            recovered = self.client.get(path, **self.auth(self.relative_token))
            self.assertEqual(recovered.json(), {"text": "다시 생성된 소식이에요.", "status": "ready"})
            adapt.assert_called_once()
        print("Post AI message processing test pass", flush=True)

    @override_settings(OPENAI_API_KEY="test-only", POST_AI_MODEL="gpt-6-luna")
    def test_ai_provider_sends_photo_and_caption_and_reads_completed_text(self):
        post_id = self.upload(caption="오늘 산책했어요").json()["id"]
        first = SimpleNamespace(status="completed", output_text="", output=[
            SimpleNamespace(type="function_call", name="search_family_memory", call_id="relation",
                            arguments=json.dumps({"query": "정아의 가족 관계"})),
        ])
        final = SimpleNamespace(status="completed", output_text="정아가 오늘 산책했어요.")
        graph = SimpleNamespace(search=AsyncMock(return_value=[]))
        with patch.object(graphiti_client, "create_graphiti", return_value=graph), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as close, \
             patch.object(post_flow, "AsyncOpenAI") as sdk:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=final)
            result = self.client.get(f"/api/posts/{post_id}/message/", **self.auth(self.relative_token))
        self.assertEqual(result.json(), {"text": "정아가 오늘 산책했어요.", "status": "ready"})
        graph.search.assert_not_awaited()
        close.assert_not_awaited()
        client.responses.create.assert_awaited_once()
        payload = client.responses.create.await_args_list[0].kwargs
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["service_tier"], "fast")
        self.assertEqual(payload["reasoning"], {"effort": "none"})
        self.assertFalse(payload["store"])
        self.assertIn("두 문장", payload["instructions"])
        content = payload["input"][0]["content"]
        self.assertIn("오늘 산책했어요", content[0]["text"])
        self.assertIn("어머니", content[0]["text"])
        self.assertEqual(content[1]["detail"], "high")
        self.assertTrue(base64.b64decode(content[1]["image_url"].split(",", 1)[1]).startswith(b"\xff\xd8"))
        self.assertEqual(client.responses.create.call_args.kwargs["input"][0]["content"], content)
        print("Post AI provider request test pass", flush=True)

    @override_settings(OPENAI_API_KEY="test-only")
    def test_ai_provider_rejects_incomplete_response(self):
        post_id = self.upload().json()["id"]
        with patch.object(graphiti_client, "create_graphiti", return_value="graph"), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as close, \
             patch.object(post_flow, "AsyncOpenAI") as sdk:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=SimpleNamespace(status="incomplete"))
            response = self.client.get(
                f"/api/posts/{post_id}/message/", **self.auth(self.relative_token)
            )
        self.assertEqual(response.json(), {"text": "", "status": "failed"})
        close.assert_not_awaited()
        print("Post AI provider failure test pass", flush=True)
