"""Account edit regressions; no network, live AI, or production database required."""
import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from apps.accounts.models import AccessToken, User
from apps.posts.models import AdaptedMessage, Post
from apps.families.models import FamilyRoom
from apps.digests.models import Digest

from .family_fixtures import add_member


class AccountProfileTests(TestCase):
    original = "Initial-River-34691!"
    replacement = "Sunset-Maple-63729!"

    def setUp(self):
        self.user = User.objects.create_user(
            username="account_owner", password=self.original, display_name="정아"
        )
        self.other = User.objects.create_user(
            username="other_owner", password=self.original, display_name="다른 가족"
        )
        self.token = AccessToken.issue(self.user)
        self.other_token = AccessToken.issue(self.other)

    def auth(self, token=None):
        return {"HTTP_AUTHORIZATION": "Bearer " + (self.token if token is None else token)}

    def update(self, body, token=None):
        return self.client.patch("/api/accounts/me/", json.dumps(body), content_type="application/json", **self.auth(token))

    def test_profile_get_and_edit_require_login(self):
        self.assertEqual(self.client.get("/api/accounts/me/").status_code, 401)
        self.assertEqual(self.client.patch("/api/accounts/me/", "{}", content_type="application/json").status_code, 401)

    def test_name_edit_preserves_username_gender_and_token(self):
        result = self.update({"name": " 새 이름 "})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["name"], "새 이름")
        self.assertEqual(result.json()["username"], "account_owner")
        self.assertNotIn("token", result.json())
        self.user.refresh_from_db()
        self.assertEqual(self.user.gender, "unknown")
        self.assertTrue(self.user.check_password(self.original))
        self.assertIsNotNone(AccessToken.from_raw(self.token))

    def test_changes_only_authenticated_user(self):
        self.assertEqual(self.update({"name": "내 이름"}).status_code, 200)
        self.other.refresh_from_db()
        self.assertEqual(self.other.display_name, "다른 가족")

    def test_username_and_user_id_cannot_be_changed(self):
        for body in ({"username": "new_user"}, {"user_id": self.other.pk}, {"is_staff": True}, {}):
            with self.subTest(body=body):
                self.assertEqual(self.update(body).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "account_owner")
        self.assertFalse(self.user.is_staff)

    def test_invalid_names_are_rejected(self):
        for name in ("", "   ", "x" * 41, None, 123):
            with self.subTest(name=name):
                self.assertEqual(self.update({"name": name}).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "정아")

    def test_tts_voice_defaults_to_male_and_can_be_changed(self):
        self.assertEqual(self.client.get("/api/accounts/me/", **self.auth()).json()["tts_voice"], "m")
        result = self.update({"tts_voice": "f"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["tts_voice"], "f")
        self.assertNotIn("token", result.json())
        self.user.refresh_from_db()
        self.assertEqual((self.user.tts_voice, self.user.display_name), ("f", "정아"))
        for voice in ("b", "", None, 1, ["m"], "male"):
            with self.subTest(voice=voice):
                self.assertEqual(self.update({"tts_voice": voice}).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.tts_voice, "f")

    def test_registration_stores_the_chosen_tts_voice(self):
        def register(username, **extra):
            return self.client.post("/api/accounts/register/", json.dumps({"username": username, "gender": "female", "name": "신규", "password": "Forest!Trail7346", **extra}), content_type="application/json")
        self.assertEqual(register("female_voice", tts_voice="f").json()["tts_voice"], "f")
        self.assertEqual(User.objects.get(username="female_voice").tts_voice, "f")
        self.assertEqual(register("default_voice").json()["tts_voice"], "m")
        self.assertEqual(register("bad_voice", tts_voice="b").status_code, 400)
        self.assertFalse(User.objects.filter(username="bad_voice").exists())

    def test_relationship_related_field_is_outside_profile_edit_scope(self):
        self.assertEqual(self.update({"name": "잘못된 수정", "gender": "female"}).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "정아")

    def test_password_fields_must_be_paired(self):
        for body in ({"current_password": self.original}, {"new_password": self.replacement}):
            with self.subTest(keys=list(body)):
                self.assertEqual(self.update(body).status_code, 400)

    def test_wrong_current_password_rolls_back_all_edits(self):
        response = self.update({"name": "저장되면 안됨", "current_password": "wrong", "new_password": self.replacement})
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "정아")
        self.assertTrue(self.user.check_password(self.original))
        self.assertIsNotNone(AccessToken.from_raw(self.token))

    def test_weak_passwords_are_rejected(self):
        for password in ("short", "1" * 15, "account_owner", "Forest!Trail", "x" * 129, None):
            with self.subTest(password=password):
                self.assertEqual(self.update({"current_password": self.original, "new_password": password}).status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.original))

    def test_password_change_rotates_own_tokens_only(self):
        second_token = AccessToken.issue(self.user)
        response = self.update({"current_password": self.original, "new_password": self.replacement})
        self.assertEqual(response.status_code, 200)
        new_token = response.json()["token"]
        for old in (self.token, second_token):
            self.assertEqual(self.client.get("/api/accounts/me/", **self.auth(old)).status_code, 401)
        self.assertEqual(self.client.get("/api/accounts/me/", **self.auth(new_token)).status_code, 200)
        self.assertEqual(self.client.get("/api/accounts/me/", **self.auth(self.other_token)).status_code, 200)

    def test_login_accepts_new_password_and_rejects_old(self):
        self.assertEqual(self.update({"current_password": self.original, "new_password": self.replacement}).status_code, 200)
        def login(password):
            return self.client.post("/api/accounts/login/", json.dumps({"username": "account_owner", "password": password}), content_type="application/json")
        self.assertEqual(login(self.original).status_code, 401)
        self.assertEqual(login(self.replacement).status_code, 200)

    def test_expired_token_cannot_edit_but_password_login_works(self):
        AccessToken.objects.filter(user=self.user).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.update({"name": "안됨"}).status_code, 401)
        response = self.client.post("/api/accounts/login/", json.dumps({"username": "account_owner", "password": self.original}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(AccessToken.from_raw(response.json()["token"]))

    def test_display_name_similarity_is_checked_on_registration(self):
        result = self.client.post("/api/accounts/register/", json.dumps({"username": "unrelated_login", "gender": "male", "name": "MapleSunset7", "password": "MapleSunset7"}), content_type="application/json")
        self.assertEqual(result.status_code, 400)
        self.assertFalse(User.objects.filter(username="unrelated_login").exists())

    def test_registration_requires_number(self):
        result = self.client.post("/api/accounts/register/", json.dumps({"username": "new_account", "gender": "male", "name": "신규", "password": "Forest!Trail"}), content_type="application/json")
        self.assertEqual(result.status_code, 400)
        self.assertIn("숫자", result.json()["error"])
        self.assertFalse(User.objects.filter(username="new_account").exists())

    def test_registration_accepts_long_password_with_number(self):
        result = self.client.post("/api/accounts/register/", json.dumps({"username": "new_account", "gender": "male", "name": "신규", "password": "Forest!Trail7346"}), content_type="application/json")
        self.assertEqual(result.status_code, 201)
        self.assertTrue(User.objects.get(username="new_account").check_password("Forest!Trail7346"))

    def test_profile_change_invalidates_related_cached_wording(self):
        room = FamilyRoom.objects.create(name="가족", invite_code="ACC001", password_hash="unused", owner=self.user)
        add_member(room, self.user)
        post = Post.objects.create(room=room, author=self.user, images=["unused.jpg"], caption="산책")
        message = AdaptedMessage.objects.create(post=post, viewer=self.other, status="ready", text="정아 소식")
        digest = Digest.objects.create(room=room, date=timezone.localdate(), status="ready", text="정아의 하루")
        digest.posts.add(post)
        self.assertEqual(self.update({"name": "새 이름"}).status_code, 200)
        message.refresh_from_db(); digest.refresh_from_db()
        self.assertEqual((message.status, message.text), ("pending", ""))
        self.assertEqual((digest.status, digest.text), ("pending", ""))

    def test_inflight_explanation_cannot_restore_a_previous_name(self):
        room = FamilyRoom.objects.create(name="가족", invite_code="ACC002", password_hash="unused", owner=self.user)
        add_member(room, self.user)
        post = Post.objects.create(room=room, author=self.user, images=["unused.jpg"], caption="산책")

        def old_explanation(*args):
            self.assertEqual(self.update({"name": "새 이름"}).status_code, 200)
            return "이전 이름으로 만든 설명"

        with patch("apps.posts.views.provider.adapt", side_effect=old_explanation):
            response = self.client.get(f"/api/posts/{post.pk}/message/", **self.auth())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "pending", "text": ""})
