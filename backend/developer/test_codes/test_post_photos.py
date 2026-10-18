"""Offline regressions: synthetic photos, isolated storage, mocked AI."""
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import Post, PostPhoto
from integrations.ai import provider


def photo(color="red"):
    data = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(data, "PNG")
    return SimpleUploadedFile("photo.png", data.getvalue(), content_type="image/png")


@override_settings(PUBLIC_ORIGIN="")
class PostPhotoTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.media = Path(temp.name)
        settings = override_settings(MEDIA_ROOT=temp.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.owner = User.objects.create_user(username="photo-owner", password="Offline-Test-123!", display_name="정아")
        self.outsider = User.objects.create_user(username="photo-other", password="Offline-Test-456!", display_name="다른 가족")
        self.room = FamilyRoom.objects.create(name="사진 가족", invite_code="PHOTO1", password_hash="unused", owner=self.owner)
        other = FamilyRoom.objects.create(name="다른 가족", invite_code="PHOTO2", password_hash="unused", owner=self.outsider)
        Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.OWNER)
        Membership.objects.create(room=other, user=self.outsider, slot=Membership.Slot.OWNER)
        self.auth = {"HTTP_AUTHORIZATION": "Bearer " + AccessToken.issue(self.owner)}
        self.other_auth = {"HTTP_AUTHORIZATION": "Bearer " + AccessToken.issue(self.outsider)}

    def upload(self, colors=("red", "blue")):
        return self.client.post("/api/posts/", {"images": [photo(c) for c in colors], "caption": "공원에 갔어요"}, **self.auth)

    def test_multiple_photos_keep_order_and_legacy_cover(self):
        result = self.upload()
        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertEqual(data["image_count"], 2)
        self.assertEqual(data["images"][0]["url"], data["image_url"])
        post = Post.objects.get()
        self.assertEqual(post.photos.get().position, 1)
        self.assertEqual(len(post.photo_files()), 2)
        for index, image in enumerate(post.photo_files()):
            with Image.open(image) as decoded:
                pixel = decoded.getpixel((0, 0))
                self.assertGreater(pixel[0 if index == 0 else 2], 240)
        feed = self.client.get("/api/posts/", **self.auth).json()["posts"][0]
        detail = self.client.get(f"/api/posts/{post.pk}/", **self.auth).json()
        self.assertEqual(feed["images"], data["images"])
        self.assertEqual(detail["images"], data["images"])

    def test_legacy_single_upload_still_works(self):
        result = self.client.post("/api/posts/", {"image": photo()}, **self.auth)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["image_count"], 1)
        self.assertEqual(PostPhoto.objects.count(), 0)

    def test_five_allowed_six_rejected(self):
        self.assertEqual(self.upload(("red",) * 5).status_code, 200)
        self.assertEqual(self.upload(("red",) * 6).status_code, 400)
        self.assertEqual(Post.objects.count(), 1)

    def test_empty_post_rejected(self):
        result = self.client.post("/api/posts/", {"caption": "  \n "}, **self.auth)
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Post.objects.exists())

    def test_mixed_fields_rejected(self):
        result = self.client.post("/api/posts/", {"image": photo(), "images": photo()}, **self.auth)
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Post.objects.exists())

    def test_invalid_second_file_leaves_no_partial_post_or_files(self):
        result = self.client.post("/api/posts/", {"images": [photo(), SimpleUploadedFile("bad.jpg", b"bad")]}, **self.auth)
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Post.objects.exists())
        self.assertFalse(any(x.is_file() for x in self.media.rglob("*")))

    @override_settings(MAX_UPLOAD_BYTES=10)
    def test_per_photo_byte_limit(self):
        self.assertEqual(self.upload().status_code, 400)
        self.assertFalse(Post.objects.exists())

    @override_settings(MAX_POST_UPLOAD_BYTES=10)
    def test_combined_byte_limit(self):
        self.assertEqual(self.upload().status_code, 400)
        self.assertFalse(Post.objects.exists())

    def test_storage_failure_rolls_back_and_cleans_first_file(self):
        from apps.posts.services import prepare_image, save_post
        storage = Post._meta.get_field("image").storage
        original = storage.save
        calls = 0

        def save(name, data, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("offline simulated storage failure")
            return original(name, data, *args, **kwargs)

        with patch.object(storage, "save", side_effect=save):
            with self.assertRaises(OSError):
                save_post(self.room, self.owner, "테스트", [prepare_image(photo()), prepare_image(photo())])
        self.assertFalse(Post.objects.exists())
        self.assertFalse(PostPhoto.objects.exists())
        self.assertFalse(any(x.is_file() for x in self.media.rglob("*")))

    def test_extra_photo_requires_auth_and_same_family(self):
        data = self.upload().json()
        path = f"/api/posts/{data['id']}/photos/{data['images'][1]['id']}/"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, **self.other_auth).status_code, 404)
        response = self.client.get(path, **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, max-age=300")
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\xff\xd8"))
        response.close()

    def test_extra_photo_cannot_be_read_through_another_post(self):
        first = self.upload().json()
        second = self.upload().json()
        path = f"/api/posts/{second['id']}/photos/{first['images'][1]['id']}/"
        self.assertEqual(self.client.get(path, **self.auth).status_code, 404)

    def test_adapt_passes_all_photos_to_existing_memory_flow(self):
        self.upload()
        post = Post.objects.get()
        with patch.object(provider, "answer_with_memory", return_value="소식") as answer:
            self.assertEqual(provider.adapt(post, "손녀"), "소식")
        self.assertEqual(answer.call_args.args[0:2], ("post_summary", self.room.pk))
        self.assertEqual([x.name for x in answer.call_args.args[3]], [x.name for x in post.photo_files()])

    def test_digest_caps_images_at_eight(self):
        self.upload(("red",) * 5)
        self.upload(("blue",) * 5)
        with patch.object(provider, "answer_with_memory", return_value="요약") as answer:
            self.assertEqual(provider.summarize(list(Post.objects.all())), "요약")
        self.assertEqual(len(answer.call_args.args[3]), 8)
