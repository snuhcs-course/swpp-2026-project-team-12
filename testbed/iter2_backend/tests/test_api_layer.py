"""End-to-end HTTP contracts for the Django API layer."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.accounts.models import AccessToken
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import AdaptedMessage, Post
from apps.replies.models import Comment, VoiceDraft
from integrations.ai.provider import AIUnavailable
from integrations.speech.provider import SpeechUnavailable

from .helpers import corrupt_upload, image_upload


User = get_user_model()


class ApiLayerFixture(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        media_override = override_settings(MEDIA_ROOT=Path(self.media_dir.name))
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.owner = User.objects.create_user("owner", password="Valid-passphrase1!", display_name="Owner")
        self.member = User.objects.create_user("member", password="Valid-passphrase1!", display_name="Member")
        self.outsider = User.objects.create_user("outsider", password="Valid-passphrase1!", display_name="Outsider")
        self.room = FamilyRoom.objects.create(name="Main family", invite_code="API001", password_hash=make_password("Room-passphrase1!"), owner=self.owner)
        other_room = FamilyRoom.objects.create(name="Other family", invite_code="API002", password_hash=make_password("Room-passphrase1!"), owner=self.outsider)
        Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.OWNER)
        Membership.objects.create(room=self.room, user=self.member, slot=Membership.Slot.SON)
        Membership.objects.create(room=other_room, user=self.outsider, slot=Membership.Slot.OWNER)
        self.owner_auth = self.auth(AccessToken.issue(self.owner))
        self.member_auth = self.auth(AccessToken.issue(self.member))
        self.outsider_auth = self.auth(AccessToken.issue(self.outsider))

    @staticmethod
    def auth(token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def post(self, caption="A family update", **payload):
        response = self.client.post("/api/posts/", {"caption": caption, **payload}, **self.owner_auth)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

class AccountApiIntegrationTests(TestCase):
    def test_register_login_profile_update_and_logout_contract(self):
        credentials = {"username": "registered-user", "name": "Registered User", "gender": "female", "password": "Valid-passphrase1!"}
        registered = self.client.post("/api/accounts/register/", data=json.dumps(credentials), content_type="application/json")
        self.assertEqual(registered.status_code, 201, registered.content)
        self.assertEqual(registered.json()["username"], credentials["username"])
        logged_in = self.client.post("/api/accounts/login/", data=json.dumps({"username": credentials["username"], "password": credentials["password"]}), content_type="application/json")
        self.assertEqual(logged_in.status_code, 200, logged_in.content)
        auth = ApiLayerFixture.auth(logged_in.json()["token"])
        profile = self.client.get("/api/accounts/me/", **auth)
        self.assertEqual(profile.status_code, 200, profile.content)
        self.assertEqual(profile.json()["name"], credentials["name"])
        changed = self.client.patch("/api/accounts/me/", data=json.dumps({"name": "Updated User"}), content_type="application/json", **auth)
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(changed.json()["name"], "Updated User")
        self.assertEqual(self.client.post("/api/accounts/logout/", **auth).status_code, 200)
        self.assertEqual(self.client.get("/api/accounts/me/", **auth).status_code, 401)


class ApiContractIntegrationTests(ApiLayerFixture):
    def test_family_lifecycle_http_contract(self):
        founder = User.objects.create_user("founder", password="Valid-passphrase1!", display_name="Founder")
        invitee = User.objects.create_user("invitee", password="Valid-passphrase1!", display_name="Invitee")
        created = self.client.post("/api/families/create/", data=json.dumps({"room_name": "New family", "password": "Valid-passphrase1!", "digest_time": "20:30"}), content_type="application/json", **self.auth(AccessToken.issue(founder)))
        self.assertEqual(created.status_code, 201, created.content)
        code = created.json()["room"]["invite_code"]
        joined = self.client.post("/api/families/join/", data=json.dumps({"invite_code": code, "password": "Valid-passphrase1!", "slot": "daughter"}), content_type="application/json", **self.auth(AccessToken.issue(invitee)))
        self.assertEqual(joined.status_code, 200, joined.content)
        self.assertEqual(len(joined.json()["room"]["members"]), 2)

    def test_post_media_comment_and_authorization_contract(self):
        self.assertEqual(self.client.get("/api/posts/").status_code, 401)
        post = self.post(images=[image_upload("first.png"), image_upload("second.png")])
        self.assertEqual(post["image_count"], 2)
        self.assertEqual(self.client.get(f"/api/posts/{post['id']}/", **self.outsider_auth).status_code, 404)
        feed = self.client.get("/api/posts/", **self.member_auth)
        self.assertEqual(feed.json()["posts"][0]["id"], post["id"])
        comment_path = f"/api/posts/{post['id']}/comments/"
        comment = self.client.post(comment_path, data=json.dumps({"text": "Nice update"}), content_type="application/json", **self.member_auth)
        self.assertEqual(comment.status_code, 200, comment.content)
        self.assertEqual(Comment.objects.filter(post_id=post["id"]).count(), 1)
        self.assertEqual(self.client.post(comment_path, data=json.dumps({"text": "  "}), content_type="application/json", **self.member_auth).status_code, 400)
        detail = self.client.get(f"/api/posts/{post['id']}/", **self.member_auth)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["comments"][0]["text"], "Nice update")
        photo = self.client.get(f"/api/posts/{post['id']}/image/", **self.member_auth)
        self.assertEqual(photo.status_code, 200)
        photo.close()
        extra_photo = self.client.get(f"/api/posts/{post['id']}/photos/{post['images'][1]['id']}/", **self.member_auth)
        self.assertEqual(extra_photo.status_code, 200)
        extra_photo.close()

    def test_family_lookup_current_settings_and_duplicate_join_contract(self):
        payload = json.dumps({"invite_code": "API001", "password": "Room-passphrase1!"})
        lookup = self.client.post("/api/families/lookup/", data=payload, content_type="application/json")
        self.assertEqual(lookup.status_code, 200, lookup.content)
        self.assertEqual(lookup.json()["id"], self.room.pk)
        current = self.client.get("/api/families/current/", **self.member_auth)
        self.assertEqual(current.status_code, 200, current.content)
        self.assertEqual(current.json()["id"], self.room.pk)
        denied = self.client.patch("/api/families/current/", data=json.dumps({"digest_time": "20:30"}), content_type="application/json", **self.member_auth)
        self.assertEqual(denied.status_code, 403)
        updated = self.client.patch("/api/families/current/", data=json.dumps({"digest_time": "20:30"}), content_type="application/json", **self.owner_auth)
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()["digest_time"], "20:30")
        duplicate = self.client.post("/api/families/join/", data=json.dumps({"invite_code": "API001", "password": "Room-passphrase1!", "slot": "son"}), content_type="application/json", **self.member_auth)
        self.assertEqual(duplicate.status_code, 409)

    def test_voice_draft_send_is_idempotent_and_private(self):
        post = self.post()
        draft = VoiceDraft.objects.create(post_id=post["id"], author=self.member, recognized="raw", converted="Cleaned reply")
        path = f"/api/replies/{draft.pk}/send/"
        sent = self.client.post(path, **self.member_auth)
        self.assertEqual(sent.status_code, 200, sent.content)
        self.assertEqual(Comment.objects.get(pk=sent.json()["id"]).source, "voice")
        retried = self.client.post(path, **self.member_auth)
        self.assertEqual(retried.status_code, 200, retried.content)
        self.assertEqual(retried.json()["id"], sent.json()["id"])
        self.assertEqual(self.client.post(path, **self.outsider_auth).status_code, 404)

    def test_rejected_upload_preserves_database_and_media_state(self):
        before = Post.objects.count()
        response = self.client.post("/api/posts/", {"caption": "Broken", "image": corrupt_upload()}, **self.owner_auth)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Post.objects.count(), before)
        self.assertEqual(list(Path(self.media_dir.name).rglob("*")), [])


class MockedProviderIntegrationTests(ApiLayerFixture):
    """Exercise the app's provider boundaries without contacting external APIs."""

    def test_mocked_openai_summary_success_and_failure_state(self):
        post = self.post()
        path = f"/api/posts/{post['id']}/message/"
        with patch("apps.posts.views.provider.adapt", return_value="Mocked family summary") as adapt:
            response = self.client.get(path, **self.member_auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"text": "Mocked family summary", "status": "ready"})
            self.client.get(path, **self.member_auth)
            adapt.assert_called_once()
        message = AdaptedMessage.objects.get(post_id=post["id"], viewer=self.member)
        self.assertEqual(message.status, "ready")
        failed_post = self.post("Summary provider failure")
        failed_path = f"/api/posts/{failed_post['id']}/message/"
        with patch("apps.posts.views.provider.adapt", side_effect=AIUnavailable("unavailable")):
            failed_summary = self.client.post(failed_path, **self.member_auth)
        self.assertEqual(failed_summary.json(), {"text": "", "status": "failed"})

    def test_mocked_graphiti_qa_success_and_unavailable_error(self):
        post = self.post()
        path = f"/api/posts/{post['id']}/questions/"
        payload = json.dumps({"question": "What happened before this?", "prior_dialogue": []})
        with patch("apps.posts.views.provider.ask", return_value="Mocked retrieved answer") as ask:
            response = self.client.post(path, data=payload, content_type="application/json", **self.member_auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["text"], "Mocked retrieved answer")
            ask.assert_called_once()
        with patch("apps.posts.views.provider.ask", side_effect=AIUnavailable("unavailable")):
            failed = self.client.post(path, data=payload, content_type="application/json", **self.member_auth)
        self.assertEqual(failed.status_code, 503)

    def test_mocked_stt_cleanup_and_tts_response_contracts(self):
        post = self.post()
        prepare_path = f"/api/posts/{post['id']}/replies/prepare/"
        with patch("apps.replies.views.provider.rewrite", return_value="Cleaned speech text") as rewrite:
            prepared = self.client.post(prepare_path, data=json.dumps({"recognized": "raw speech"}), content_type="application/json", **self.member_auth)
            self.assertEqual(prepared.status_code, 200)
            self.assertEqual(prepared.json()["converted"], "Cleaned speech text")
            rewrite.assert_called_once()
        self.assertEqual(VoiceDraft.objects.filter(post_id=post["id"], author=self.member).count(), 1)
        with patch("apps.replies.views.provider.rewrite", side_effect=AIUnavailable("unavailable")):
            failed_cleanup = self.client.post(prepare_path, data=json.dumps({"recognized": "raw speech"}), content_type="application/json", **self.member_auth)
        self.assertEqual(failed_cleanup.status_code, 503)
        with patch("integrations.speech.views.provider.synthesize", return_value=b"mock-mp3") as synthesize:
            spoken = self.client.post("/api/speech/", data=json.dumps({"text": "Read this"}), content_type="application/json", **self.member_auth)
            self.assertEqual(spoken.status_code, 200)
            self.assertEqual(spoken["Content-Type"], "audio/mpeg")
            self.assertEqual(spoken.content, b"mock-mp3")
            synthesize.assert_called_once_with("Read this", self.room.pk)
        with patch("integrations.speech.views.provider.synthesize", side_effect=SpeechUnavailable("unavailable")):
            failed_tts = self.client.post("/api/speech/", data=json.dumps({"text": "Read this"}), content_type="application/json", **self.member_auth)
        self.assertEqual(failed_tts.status_code, 503)

    def test_mocked_stt_transcription_success_and_unavailable_error(self):
        post = self.post()
        path = f"/api/posts/{post['id']}/replies/transcribe/"
        audio = SimpleUploadedFile("recording.m4a", b"\x00\x00\x00\x18ftypisom", content_type="audio/mp4")
        with patch("integrations.speech.views.provider.transcribe", return_value="Recognized speech") as transcribe:
            response = self.client.post(path, {"audio": audio}, **self.member_auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["recognized"], "Recognized speech")
            transcribe.assert_called_once()
        audio = SimpleUploadedFile("recording.m4a", b"\x00\x00\x00\x18ftypisom", content_type="audio/mp4")
        with patch("integrations.speech.views.provider.transcribe", side_effect=SpeechUnavailable("unavailable")):
            failed = self.client.post(path, {"audio": audio}, **self.member_auth)
        self.assertEqual(failed.status_code, 503)

