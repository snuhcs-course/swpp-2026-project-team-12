"""Coverage for backend validation, family, and post service modules."""
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils.datastructures import MultiValueDict
from PIL import Image

from apps.api import APIError, required
from apps.families.models import FamilyRoom
from apps.families.services import parse_time
from apps.families.utils import relationship
from developer.test_codes.family_fixtures import add_member, link_parent
from apps.posts.models import Post
from apps.posts.services import prepare_image, prepare_uploads, serialize

from .helpers import corrupt_upload, image_upload


User = get_user_model()


class ServiceLayerTests(TestCase):
    """Rules that must be deterministic without an HTTP request."""

    def setUp(self):
        self.owner = User.objects.create_user("owner", password="Valid-passphrase1!", display_name="Owner")
        self.son = User.objects.create_user("son", password="Valid-passphrase1!", display_name="Son", gender=User.Gender.MALE)
        self.room = FamilyRoom.objects.create(name="Service family", invite_code="SERV01", password_hash="x", owner=self.owner)
        add_member(self.room, self.owner)
        add_member(self.room, self.son, -1)
        link_parent(self.room, self.owner, self.son)

    def test_validation_and_relationship_service_contracts(self):
        self.assertEqual(required({"caption": "  hello  "}, "caption", 20), "hello")
        self.assertEqual(parse_time("09:30").isoformat(), "09:30:00")
        self.assertNotEqual(relationship(self.owner, self.son, self.room), relationship(self.son, self.owner, self.room))
        for invalid in ("", " " * 3, 7):
            with self.subTest(invalid=invalid):
                with self.assertRaises(APIError):
                    required({"caption": invalid}, "caption", 20)
        for invalid in ("09:30:01", "not-a-time", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(APIError):
                    parse_time(invalid)

    def test_post_media_service_normalizes_files_and_enforces_limits(self):
        prepared = prepare_image(image_upload(size=(2200, 1100)))
        with Image.open(prepared) as stored:
            self.assertEqual(stored.format, "JPEG")
            self.assertLessEqual(max(stored.size), settings.MAX_IMAGE_DIMENSION)
        with self.assertRaises(APIError):
            prepare_image(corrupt_upload())
        request = SimpleNamespace(FILES=MultiValueDict({"images": [image_upload(f"{index}.png") for index in range(6)]}))
        with self.assertRaises(APIError):
            prepare_uploads(request)

    def test_feed_serializer_preserves_contract_for_viewer(self):
        post = Post.objects.create(room=self.room, author=self.owner, caption="Weekend walk")
        request = RequestFactory().get("/api/posts/")
        request.user = self.son
        data = serialize(post, request)
        self.assertEqual(data["caption"], "Weekend walk")
        self.assertEqual(data["image_count"], 0)
        self.assertEqual(data["comment_count"], 0)
        self.assertTrue(data["relationship"])
