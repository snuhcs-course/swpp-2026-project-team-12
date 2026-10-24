"""Text-only posts across feed, comments, image endpoints and AI adapters; no live APIs."""
import io
import json
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom
from apps.posts.models import Post
from apps.posts.services import save_post
from apps.api import APIError
from integrations.ai import provider

from .family_fixtures import add_member


def photo():
    output = io.BytesIO()
    Image.new("RGB", (48, 32), "blue").save(output, "PNG")
    return SimpleUploadedFile("example.png", output.getvalue(), content_type="image/png")


@override_settings(PUBLIC_ORIGIN="")
class TextPostTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.media = Path(temporary.name)
        configured = override_settings(MEDIA_ROOT=temporary.name)
        configured.enable(); self.addCleanup(configured.disable)
        self.owner = User.objects.create_user(username="text-owner", password="Offline-Pass-123!", display_name="정아")
        self.other = User.objects.create_user(username="text-other", password="Offline-Pass-456!", display_name="다른 가족")
        self.room = FamilyRoom.objects.create(owner=self.owner, name="우리 가족", invite_code="TEXT01", password_hash="unused")
        other_room = FamilyRoom.objects.create(owner=self.other, name="다른 가족", invite_code="TEXT02", password_hash="unused")
        add_member(self.room, self.owner)
        add_member(other_room, self.other)
        self.auth = {"HTTP_AUTHORIZATION": "Bearer " + AccessToken.issue(self.owner)}
        self.other_auth = {"HTTP_AUTHORIZATION": "Bearer " + AccessToken.issue(self.other)}

    def upload(self, caption="오늘 산책을 다녀왔어요.", **files):
        return self.client.post("/api/posts/", {"caption": caption, **files}, **self.auth)

    def test_text_only_has_no_images_or_files(self):
        response = self.upload("  오늘 산책을 다녀왔어요.  ")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["caption"], "오늘 산책을 다녀왔어요.")
        self.assertEqual((data["image_url"], data["images"], data["image_count"]), ("", [], 0))
        post = Post.objects.get()
        self.assertEqual(post.images, [])
        self.assertEqual(post.photo_files(), [])
        self.assertFalse(any(item.is_file() for item in self.media.rglob("*")))

    def test_empty_post_is_rejected(self):
        for data in ({}, {"caption": ""}, {"caption": "  \n\t "}):
            with self.subTest(data=data):
                self.assertEqual(self.client.post("/api/posts/", data, **self.auth).status_code, 400)
        self.assertFalse(Post.objects.exists())

    def test_save_service_also_rejects_empty_content(self):
        with self.assertRaises(APIError):
            save_post(self.room, self.owner, " \n", [])
        self.assertFalse(Post.objects.exists())

    def test_caption_limit(self):
        self.assertEqual(self.upload("가" * 2000).status_code, 200)
        self.assertEqual(self.upload("가" * 2001).status_code, 400)
        self.assertEqual(Post.objects.count(), 1)

    def test_photo_only_and_photo_with_text_remain_supported(self):
        for caption in ("", "가족과 함께한 점심"):
            with self.subTest(caption=caption):
                result = self.upload(caption, image=photo())
                self.assertEqual(result.status_code, 200, result.content)
                self.assertEqual(result.json()["image_count"], 1)
                self.assertEqual(result.json()["caption"], caption)

    def test_invalid_photo_is_not_silently_dropped(self):
        result = self.upload(image=SimpleUploadedFile("invalid.jpg", b"not an image"))
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Post.objects.exists())

    def test_feed_detail_and_photo_endpoint(self):
        uploaded = self.upload().json()
        pk = uploaded["id"]
        self.assertEqual(self.client.get("/api/posts/", **self.auth).json()["posts"][0]["images"], [])
        detail = self.client.get(f"/api/posts/{pk}/", **self.auth)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["image_url"], "")
        for path in (f"/api/posts/{pk}/image/", f"/api/posts/{pk}/images/12345/"):
            self.assertEqual(self.client.get(path, **self.auth).status_code, 404)
            self.assertEqual(self.client.get(path, **self.other_auth).status_code, 404)
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(f"/api/posts/{pk}/", **self.other_auth).status_code, 404)

    def test_post_requires_login_and_family(self):
        self.assertEqual(self.client.post("/api/posts/", {"caption": "소식"}).status_code, 401)
        user = User.objects.create_user(username="text-no-room", password="Offline-Pass-789!", display_name="미가입자")
        auth = {"HTTP_AUTHORIZATION": "Bearer " + AccessToken.issue(user)}
        self.assertEqual(self.client.post("/api/posts/", {"caption": "소식"}, **auth).status_code, 403)
        self.assertFalse(Post.objects.exists())

    def test_text_comment_on_text_only_post(self):
        pk = self.upload().json()["id"]
        path = f"/api/posts/{pk}/comments/"
        result = self.client.post(path, json.dumps({"text": "산책 다녀오셨군요!"}), content_type="application/json", **self.auth)
        self.assertEqual(result.status_code, 200, result.content)
        detail = self.client.get(f"/api/posts/{pk}/", **self.auth).json()
        self.assertEqual(detail["comments"][0]["text"], "산책 다녀오셨군요!")

    def test_adapt_receives_text_without_trying_to_open_a_photo(self):
        self.upload()
        post = Post.objects.get()
        with patch.object(provider, "answer_with_memory", return_value="산책을 다녀오셨대요.") as answer:
            self.assertEqual(provider.adapt(post, "어머니"), "산책을 다녀오셨대요.")
        self.assertEqual(answer.call_args.args[:2], ("post_summary", self.room.pk))
        self.assertEqual(json.loads(answer.call_args.args[2])["원문"], post.caption)
        self.assertEqual(answer.call_args.args[3], [])

    def test_message_endpoint_supports_text_only_post(self):
        pk = self.upload().json()["id"]
        with patch.object(provider, "answer_with_memory", return_value="산책을 다녀오셨대요."):
            response = self.client.get(f"/api/posts/{pk}/message/", **self.auth)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"status": "ready", "text": "산책을 다녀오셨대요."})

    def test_text_only_digest_includes_original_post_and_no_photo(self):
        self.upload()
        post = Post.objects.get()
        day = timezone.localdate() - timedelta(days=2)
        Post.objects.filter(pk=post.pk).update(created_at=timezone.make_aware(datetime.combine(day, time(12))))
        with patch.object(provider, "answer_with_memory", return_value="가족이 산책을 다녀왔어요.") as answer:
            response = self.client.get(f"/api/digests/?date={day.isoformat()}", **self.auth)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual(response.json()["posts"][0]["images"], [])
        self.assertEqual(answer.call_args.args[0], "digest")
        self.assertEqual(answer.call_args.args[3], [])

    def test_mixed_digest_keeps_both_captions_and_only_real_images(self):
        self.upload("글만 있는 소식")
        self.upload("사진이 있는 소식", image=photo())
        posts = list(Post.objects.order_by("pk"))
        with patch.object(provider, "answer_with_memory", return_value="하루 소식") as answer:
            self.assertEqual(provider.summarize(posts), "하루 소식")
        captions = [item["원문"] for item in json.loads(answer.call_args.args[2])]
        self.assertEqual(captions, ["글만 있는 소식", "사진이 있는 소식"])
        self.assertEqual(len(answer.call_args.args[3]), 1)
        self.assertTrue(answer.call_args.args[3][0])
