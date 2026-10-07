import io
from html import escape
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import Post


SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"
TEST_MEDIA_DIR = Path(__file__).resolve().parents[1] / "test_media"
POST_REPORT = TEST_MEDIA_DIR / "posts_report.html"


def sample_image(name="sample_img_1.png"):
    return SimpleUploadedFile(name, (SAMPLES_DIR / name).read_bytes(), content_type="image/png")


def write_post_report(posts):
    rows = []
    for post in posts:
        image_path = escape(quote(post["image"], safe="/"), quote=True)
        cells = (
            post["test"], post["id"], post["room_id"], post["room_name"],
            post["author_id"], post["author_name"], post["image"],
            post["caption"], post["created_at"],
        )
        rows.append(
            "<tr>"
            + f'<td><a href="{image_path}"><img src="{image_path}" alt="Post image"></a></td>'
            + "".join(f"<td>{escape(str(value))}</td>" for value in cells)
            + "</tr>"
        )

    POST_REPORT.parent.mkdir(parents=True, exist_ok=True)
    POST_REPORT.write_text(
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<title>Post test DB</title>"
        "<style>body{font:15px sans-serif;margin:2rem;color:#222}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:.6rem;"
        "text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#f3f3f3}"
        "img{max-width:180px;max-height:140px}td:nth-child(2){max-width:220px}</style>"
        "</head><body><h1>Post test DB</h1>"
        "<p>Each test uses an isolated database, so post IDs may repeat. "
        "This report shows rows captured during the latest test run.</p>"
        "<table><thead><tr><th>Preview</th><th>Test</th><th>ID</th><th>Room ID</th>"
        "<th>Room</th><th>Author ID</th><th>Author</th><th>Image path</th>"
        "<th>Caption</th><th>Created at</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>",
        encoding="utf-8",
    )


class PostAPITests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.post_snapshots = []

    def setUp(self):
        media_settings = override_settings(MEDIA_ROOT=TEST_MEDIA_DIR)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

        self.owner = User.objects.create_user(
            username="owner", password="Owner-Passphrase1!", display_name="정아", gender=User.Gender.FEMALE
        )
        self.relative = User.objects.create_user(
            username="relative", password="Relative-Passphrase1!", display_name="준호"
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
        Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.OWNER)
        Membership.objects.create(room=self.room, user=self.relative, slot=Membership.Slot.SON)
        Membership.objects.create(room=self.other_room, user=self.outsider, slot=Membership.Slot.OWNER)
        self.owner_token = AccessToken.issue(self.owner)
        self.relative_token = AccessToken.issue(self.relative)
        self.outsider_token = AccessToken.issue(self.outsider)

    def tearDown(self):
        for post in Post.objects.select_related("room", "author").order_by("pk"):
            type(self).post_snapshots.append({
                "test": self._testMethodName,
                "id": post.pk,
                "room_id": post.room_id,
                "room_name": post.room.name,
                "author_id": post.author_id,
                "author_name": post.author.display_name,
                "image": post.image.name,
                "caption": post.caption,
                "created_at": timezone.localtime(post.created_at).isoformat(timespec="seconds"),
            })
        super().tearDown()

    @classmethod
    def tearDownClass(cls):
        write_post_report(cls.post_snapshots)
        super().tearDownClass()
        print(
            f"Post test DB and images ({len(cls.post_snapshots)} posts): "
            f"{POST_REPORT.relative_to(settings.BASE_DIR.parent).as_posix()}",
            flush=True,
        )

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def upload(self, caption="", image=None):
        return self.client.post(
            "/api/posts/",
            {"image": image if image is not None else sample_image(),
             "caption": caption},
            **self.auth(self.owner_token),
        )

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
