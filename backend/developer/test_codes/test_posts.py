import base64
import io
import json
import os
from contextlib import nullcontext
from datetime import timedelta
from html import escape
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import AdaptedMessage, Post
from integrations.ai import provider


SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"
TEST_MEDIA_DIR = Path(__file__).resolve().parents[1] / "test_media"
POST_REPORT = TEST_MEDIA_DIR / "posts_report.html"
LIVE_POST_REPORT = TEST_MEDIA_DIR / "grandma_ai_report.html"
MOCK_POST_REPORT = TEST_MEDIA_DIR / "grandma_mock_report.html"


def sample_image(name="sample_img_1.png"):
    return SimpleUploadedFile(name, (SAMPLES_DIR / name).read_bytes(), content_type="image/png")


def write_post_report(posts, report_path=POST_REPORT, summary_mode="live"):
    rows = []
    grandma_cards = []
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
        if post.get("grandma_summary"):
            grandma_cards.append(
                '<article class="card">'
                + f'<a href="{image_path}"><img src="{image_path}" alt="게시글 사진"></a>'
                + '<div><h3>정아의 게시글</h3>'
                + f'<p>{escape(post["caption"])}</p>'
                + '<h3>경자(친할머니)가 보는 요약</h3>'
                + f'<p>{escape(post["grandma_summary"])}</p></div>'
                + '</article>'
            )

    grandma_section = (
        "<h2>정아의 게시글 → 경자 관점 요약</h2>"
        + ("<p>아래 요약은 경자 계정으로 요청한 실제 OpenAI 응답입니다.</p>"
           if summary_mode == "live" else "<p>아래 요약은 테스트용 모의 응답입니다.</p>")
        + "".join(grandma_cards)
        if grandma_cards else ""
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<title>Post test DB</title>"
        "<style>body{font:15px sans-serif;margin:2rem;color:#222}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:.6rem;"
        "text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#f3f3f3}"
        "img{max-width:180px;max-height:140px}td:nth-child(2){max-width:220px}"
        ".card{display:flex;gap:1.5rem;align-items:start;border:1px solid #ccc;padding:1rem;"
        "margin:1rem 0;max-width:780px}.card img{max-width:260px;max-height:220px}"
        ".card h3{margin:.2rem 0}.card p{margin:.3rem 0 1rem}</style>"
        "</head><body><h1>Post test DB</h1>"
        "<p>Each test uses an isolated database, so post IDs may repeat. "
        "This report shows rows captured during the latest test run.</p>"
        + grandma_section
        + "<h2>게시글 DB 행</h2>"
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
        cls.grandma_summary_mode = None

    def setUp(self):
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
        Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.OWNER)
        Membership.objects.create(room=self.room, user=self.relative, slot=Membership.Slot.SON)
        Membership.objects.create(room=self.other_room, user=self.outsider, slot=Membership.Slot.OWNER)
        self.owner_token = AccessToken.issue(self.owner)
        self.relative_token = AccessToken.issue(self.relative)
        self.outsider_token = AccessToken.issue(self.outsider)

    def tearDown(self):
        for post in Post.objects.select_related("room", "author").order_by("pk"):
            grandma_message = post.messages.filter(
                viewer__display_name="경자", status="ready"
            ).first()
            type(self).post_snapshots.append({
                "test": self._testMethodName,
                "id": post.pk,
                "room_id": post.room_id,
                "room_name": post.room.name,
                "author_id": post.author_id,
                "author_name": post.author.display_name,
                "image": post.image.name,
                "caption": post.caption,
                "grandma_summary": grandma_message.text if grandma_message else "",
                "created_at": timezone.localtime(post.created_at).isoformat(timespec="seconds"),
            })
        super().tearDown()

    @classmethod
    def tearDownClass(cls):
        write_post_report(cls.post_snapshots, summary_mode=cls.grandma_summary_mode)
        if any(post["grandma_summary"] for post in cls.post_snapshots):
            report = LIVE_POST_REPORT if cls.grandma_summary_mode == "live" else MOCK_POST_REPORT
            write_post_report(cls.post_snapshots, report, summary_mode=cls.grandma_summary_mode)
        super().tearDownClass()
        print(
            f"Post test DB and images ({len(cls.post_snapshots)} posts): "
            f"{POST_REPORT.relative_to(settings.BASE_DIR.parent).as_posix()}",
            flush=True,
        )
        if any(post["grandma_summary"] for post in cls.post_snapshots):
            print(
                f"Grandma {cls.grandma_summary_mode} AI report: "
                f"{report.relative_to(settings.BASE_DIR.parent).as_posix()}",
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

    def test_grandma_post_summaries(self):
        use_mock = os.getenv("MOCK_AI_TESTS") == "1"
        type(self).grandma_summary_mode = "mock" if use_mock else "live"
        if not use_mock and not settings.OPENAI_API_KEY:
            self.skipTest("Set OPENAI_API_KEY for live summaries, or MOCK_AI_TESTS=1 for fixed responses")

        # Re-create the seven members from test_families.py in this isolated test database.
        family = (
            ("paternal_grandma", "경자", User.Gender.FEMALE, Membership.Slot.GRANDMA_FATHER),
            ("maternal_grandma", "선희", User.Gender.FEMALE, Membership.Slot.GRANDMA_MOTHER),
            ("father", "병호", User.Gender.MALE, Membership.Slot.FATHER),
            ("mother", "지현", User.Gender.FEMALE, Membership.Slot.MOTHER),
            ("daughter", "수아", User.Gender.FEMALE, Membership.Slot.DAUGHTER),
        )
        for username, name, gender, slot in family:
            user = User.objects.create_user(
                username=username, password="Relative-Passphrase1!", display_name=name, gender=gender
            )
            Membership.objects.create(room=self.room, user=user, slot=slot)
            if slot == Membership.Slot.GRANDMA_FATHER:
                grandma_token = AccessToken.issue(user)
        self.assertEqual(
            {member.slot: member.user.display_name for member in self.room.members.select_related("user")},
            {
                Membership.Slot.OWNER: "정아",
                Membership.Slot.GRANDMA_FATHER: "경자",
                Membership.Slot.GRANDMA_MOTHER: "선희",
                Membership.Slot.FATHER: "병호",
                Membership.Slot.MOTHER: "지현",
                Membership.Slot.SON: "준호",
                Membership.Slot.DAUGHTER: "수아",
            },
        )

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
        print(f"Grandma {type(self).grandma_summary_mode} AI summaries test pass", flush=True)

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

    @override_settings(OPENAI_API_KEY="test-only", OPENAI_MODEL="gpt-4.1-mini")
    def test_ai_provider_sends_photo_and_caption_and_reads_completed_text(self):
        post_id = self.upload(caption="오늘 산책했어요").json()["id"]
        response = {
            "status": "completed",
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "정아가 오늘 산책했어요."}
            ]}],
        }
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as call:
            result = self.client.get(f"/api/posts/{post_id}/message/", **self.auth(self.relative_token))
        self.assertEqual(result.json(), {"text": "정아가 오늘 산책했어요.", "status": "ready"})
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "gpt-4.1-mini")
        self.assertFalse(payload["store"])
        content = payload["input"][0]["content"]
        self.assertIn("오늘 산책했어요", content[0]["text"])
        self.assertIn("어머니", content[0]["text"])
        self.assertEqual(content[1]["detail"], "low")
        self.assertTrue(base64.b64decode(content[1]["image_url"].split(",", 1)[1]).startswith(b"\xff\xd8"))
        print("Post AI provider request test pass", flush=True)

    @override_settings(OPENAI_API_KEY="test-only")
    def test_ai_provider_rejects_incomplete_response(self):
        post_id = self.upload().json()["id"]
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"status":"incomplete","output":[]}')):
            response = self.client.get(
                f"/api/posts/{post_id}/message/", **self.auth(self.relative_token)
            )
        self.assertEqual(response.json(), {"text": "", "status": "failed"})
        print("Post AI provider failure test pass", flush=True)
