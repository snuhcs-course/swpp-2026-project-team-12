"""Offline integration checks for web serving and the browser's API contract.

Run from the repository root: python backend/manage.py test web
"""

import io
import json
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image


class WebServingTests(SimpleTestCase):
    def test_entrypoint_and_modules_are_served_without_debug_static_handler(self):
        with override_settings(DEBUG=False):
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            html = b"".join(response.streaming_content).decode()
            self.assertIn('lang="ko"', html)
            self.assertIn('type="module"', html)
            self.assertIn('script-src \'self\'', response["Content-Security-Policy"])
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            for name, content_type in [("app.js", "text/javascript"), ("api.js", "text/javascript"),
                                       ("icons.js", "text/javascript"), ("styles.css", "text/css"),
                                       ("favicon.svg", "image/svg+xml"), ("todak_joy.gif", "image/gif")]:
                with self.subTest(name=name):
                    response = self.client.get("/web/assets/" + name)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(content_type, response["Content-Type"])
                    self.assertTrue(b"".join(response.streaming_content))

    def test_server_does_not_expose_sources_secrets_or_unknown_paths(self):
        for path in ["/web/assets/run.py", "/web/assets/.env", "/web/assets/../requirements.txt",
                     "/web/index.html", "/.env", "/web/assets/missing.js", "/api/missing/"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post("/").status_code, 405)
        self.assertEqual(self.client.get("/api/test_reply/").json(), {"status": "ok"})


class WebJourneyTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        configured = override_settings(MEDIA_ROOT=temporary.name, PUBLIC_ORIGIN="https://android.example")
        configured.enable()
        self.addCleanup(configured.disable)

    def request(self, path, data, token=None, method="post"):
        return getattr(self.client, method)(path, json.dumps(data), content_type="application/json",
                                          **({"HTTP_AUTHORIZATION": "Bearer " + token} if token else {}))

    def register(self, username):
        response = self.request("/api/accounts/register/", {
            "username": username, "name": "웹 가족", "password": "Web-Offline-Test-438!",
        })
        self.assertEqual(response.status_code, 201)
        return response.json()["token"]

    def test_shared_account_room_multiphoto_comment_and_private_images(self):
        token = self.register("web-owner")
        auth = {"HTTP_AUTHORIZATION": "Bearer " + token}
        room = self.request("/api/families/create/", {"room_name": "웹 테스트 가족", "password": "room-password"}, token)
        self.assertEqual(room.status_code, 201)
        room = room.json()["room"]
        output = io.BytesIO()
        Image.new("RGB", (20, 30), "#c8aa80").save(output, "PNG")
        files = [SimpleUploadedFile(f"photo-{index}.png", output.getvalue(), "image/png") for index in range(2)]
        response = self.client.post("/api/posts/", {"caption": "브라우저에서 사진 두 장", "images": files}, **auth)
        self.assertEqual(response.status_code, 200)
        post = response.json()
        self.assertEqual(post["image_count"], 2)
        self.assertTrue(post["images"][0]["url"].startswith("https://android.example/"))
        for photo in post["images"]:
            path = f'/api/posts/{post["id"]}/image/' if photo["id"] == 0 else f'/api/posts/{post["id"]}/photos/{photo["id"]}/'
            self.assertEqual(self.client.get(path).status_code, 401)
            image = self.client.get(path, **auth)
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image["Content-Type"], "image/jpeg")
            image.close()
        comment = self.request(f'/api/posts/{post["id"]}/comments/', {"text": "따뜻한 안부를 전해요"}, token)
        self.assertEqual(comment.status_code, 200)
        detail = self.client.get(f'/api/posts/{post["id"]}/', **auth).json()
        self.assertEqual(detail["comments"][0]["text"], "따뜻한 안부를 전해요")
        other = self.register("web-member")
        joined = self.request("/api/families/join/", {"invite_code": room["invite_code"], "password": "room-password", "slot": "daughter"}, other)
        self.assertEqual(joined.status_code, 200)
        self.assertEqual(len(joined.json()["room"]["members"]), 2)
        unrelated = self.register("web-unrelated")
        self.request("/api/families/create/", {"room_name": "다른 가족", "password": "another-password"}, unrelated)
        self.assertEqual(self.client.get(f'/api/posts/{post["id"]}/', HTTP_AUTHORIZATION="Bearer " + unrelated).status_code, 404)

    def test_summary_question_search_and_profile_contract_without_external_calls(self):
        token = self.register("web-ai")
        auth = {"HTTP_AUTHORIZATION": "Bearer " + token}
        self.request("/api/families/create/", {"room_name": "오프라인 테스트", "password": "room-password"}, token)
        post = self.client.post("/api/posts/", {"caption": "가족이 함께 산책했어요."}, **auth).json()
        with patch("apps.posts.views.provider.adapt", return_value="함께 산책한 하루예요."):
            summary = self.client.post(f'/api/posts/{post["id"]}/message/', **auth).json()
            self.assertEqual(summary["status"], "ready")
        with patch("apps.posts.views.provider.ask", return_value="산책 이야기예요."):
            answer = self.request(f'/api/posts/{post["id"]}/questions/', {"question": "어떤 하루였어?", "prior_dialogue": []}, token)
            self.assertEqual(answer.json()["text"], "산책 이야기예요.")
        with patch("apps.searching.services.search_history", return_value={"text": "산책한 기억", "memories": []}):
            self.assertEqual(self.request("/api/searching/history/", {"question": "산책 이야기"}, token).json()["text"], "산책한 기억")
        changed = self.request("/api/accounts/me/", {"name": "새 이름"}, token, method="patch")
        self.assertEqual(changed.json()["name"], "새 이름")
        self.assertEqual(self.client.get("/api/digests/history/", **auth).status_code, 200)
        self.assertEqual(self.client.post("/api/accounts/logout/", **auth).status_code, 200)
        self.assertEqual(self.client.get("/api/accounts/me/", **auth).status_code, 401)
