import hashlib
import json
import sys
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import AccessToken, User


class AccountAuthenticationTests(TestCase):
    password = "S3cure-MyPassphrase!"
    registered_account_snapshot = None
    registered_token_snapshot = None

    @staticmethod
    def print_db_rows(model, records):
        table_name = model._meta.db_table
        fields = [field.attname for field in model._meta.concrete_fields]
        print(f"{table_name} ({len(records)} rows)")
        for index, record in enumerate(records, start=1):
            print(f"  Row {index}")
            for field in fields:
                value = record[field]
                print(f"    {field:<16} | {value if value is not None else 'NULL'}")

    @classmethod
    def tearDownClass(cls):
        if cls.registered_account_snapshot is not None:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            print("Test DB after registration:")
            cls.print_db_rows(User, cls.registered_account_snapshot)
            cls.print_db_rows(AccessToken, cls.registered_token_snapshot)
            sys.stdout.flush()
        super().tearDownClass()

    def post(self, path, data, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(path, json.dumps(data), content_type="application/json", **headers)

    def register(self, **changes):
        data = {"username": "SampleID", "password": self.password, "name": "하나"}
        data.update(changes)
        return self.post("/api/accounts/register/", data)

    def test_registration_creates_an_account_and_hashed_session(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "no-store")
        token = response.json()["token"]
        user = User.objects.get(username="sampleid")
        self.assertTrue(user.check_password(self.password))
        self.assertNotEqual(user.password, self.password)
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(AccessToken.objects.filter(digest=hashlib.sha256(token.encode()).hexdigest()).exists())
        self.assertFalse(AccessToken.objects.filter(digest=token).exists())

        profile = self.client.get("/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["username"], "sampleid")

        second_response = self.register(username="SecondID", name="둘")
        self.assertEqual(second_response.status_code, 201)
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(User.objects.get(username="secondid").display_name, "둘")
        type(self).registered_account_snapshot = list(
            User.objects.order_by("id").values()
        )
        type(self).registered_token_snapshot = list(AccessToken.objects.order_by("id").values())
        print("Registration test pass", flush=True)

    def test_login_and_logout_revoke_only_the_presented_token(self):
        first = self.register().json()["token"]
        bad = self.post("/api/accounts/login/", {"username": "SAMPLEID", "password": "wrong"})
        self.assertEqual(bad.status_code, 401)
        self.assertNotIn("token", bad.json())

        login = self.post("/api/accounts/login/", {"username": "SAMPLEID", "password": self.password})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login["Cache-Control"], "no-store")
        second = login.json()["token"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.post("/api/accounts/logout/", {}, second).status_code, 200)
        self.assertEqual(self.client.get("/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {second}").status_code, 401)
        self.assertEqual(self.client.get("/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {first}").status_code, 200)
        print("Login test pass", flush=True)

    def test_registration_rejects_weak_password_and_duplicate_username(self):
        self.assertEqual(self.register(password="1234567890").status_code, 400)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register(username="sampleid").status_code, 409)
        self.assertEqual(User.objects.count(), 1)
        print("Registration validation test pass", flush=True)

    def test_expired_or_inactive_sessions_cannot_authenticate(self):
        token = self.register().json()["token"]
        AccessToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get("/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 401)

        user = User.objects.get(username="sampleid")
        user.is_active = False
        user.save(update_fields=["is_active"])
        AccessToken.objects.update(expires_at=timezone.now() + timedelta(days=1))
        self.assertEqual(self.client.get("/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 401)
        self.assertEqual(self.post("/api/accounts/login/", {"username": "sampleid", "password": self.password}).status_code, 401)
        print("Session validation test pass", flush=True)

    def test_registration_requires_json_and_valid_username(self):
        response = self.client.post("/api/accounts/register/", {"username": "sampleid"})
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.register(username="bad name").status_code, 400)
        self.assertEqual(User.objects.count(), 0)
        print("Registration request test pass", flush=True)
