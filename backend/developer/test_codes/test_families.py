import json
import sys
import unicodedata
from datetime import time

from django.contrib.auth.hashers import check_password
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom, Membership


class FamilySchemaTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="Owner-Passphrase1!", display_name="하나")
        self.member = User.objects.create_user(username="member", password="Member-Passphrase1!", display_name="둘")
        self.room = FamilyRoom.objects.create(
            name="우리 가족", invite_code="ROOM01", password_hash="hashed", owner=self.owner
        )

    def test_room_defaults_and_owner_protection(self):
        self.assertEqual(self.room.digest_time, time(21))
        self.assertIsNotNone(self.room.created_at)
        self.assertEqual(Membership.objects.count(), 0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FamilyRoom.objects.create(
                name="Duplicate code", invite_code="ROOM01", password_hash="hashed", owner=self.member
            )
        with self.assertRaises(ProtectedError):
            self.owner.delete()
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())
        print("Family room test pass", flush=True)

    def test_membership_is_unique_per_user_and_slot_within_a_room(self):
        Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.OWNER)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.FATHER)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(room=self.room, user=self.member, slot=Membership.Slot.OWNER)

        second_room = FamilyRoom.objects.create(
            name="Another family", invite_code="ROOM02", password_hash="hashed", owner=self.member
        )
        Membership.objects.create(room=second_room, user=self.owner, slot=Membership.Slot.OWNER)
        self.assertEqual(Membership.objects.count(), 2)
        print("Family membership test pass", flush=True)

    def test_deleting_a_room_removes_its_memberships(self):
        Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.OWNER)
        self.room.delete()
        self.assertFalse(Membership.objects.exists())
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())
        print("Family deletion test pass", flush=True)


class FamilyWorkflowTests(TestCase):
    family_tree_snapshot = None

    @staticmethod
    def graph_row(*nodes):
        def width(value):
            return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in value)

        row = ""
        cursor = 0
        for center, label in nodes:
            left = max(center - width(label) // 2, cursor)
            row += " " * (left - cursor) + label
            cursor = left + width(label)
        return row.rstrip()

    @classmethod
    def tearDownClass(cls):
        if cls.family_tree_snapshot is not None:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            room_name, members = cls.family_tree_snapshot
            print(f"Test family graph: {room_name} (arrows point from child to parent)")
            print(cls.graph_row(
                (15, f"[{members[Membership.Slot.GRANDMA_FATHER]} · 친할머니]"),
                (65, f"[{members[Membership.Slot.GRANDMA_MOTHER]} · 외할머니]"),
            ))
            print(cls.graph_row((15, "↑"), (65, "↑")))
            print(cls.graph_row(
                (15, f"[{members[Membership.Slot.FATHER]} · 아버지]"),
                (65, f"[{members[Membership.Slot.MOTHER]} · 어머니]"),
            ))
            print(cls.graph_row((19, "↖"), (61, "↗")))
            for left, right in ((24, 56), (29, 51), (34, 46)):
                print(cls.graph_row((left, "╲"), (right, "╱")))
            print(cls.graph_row((40, f"[{members[Membership.Slot.OWNER]} · 본인]")))
            print(cls.graph_row((36, "↗"), (44, "↖")))
            for left, right in ((32, 48), (28, 52), (24, 56)):
                print(cls.graph_row((left, "╱"), (right, "╲")))
            print(cls.graph_row(
                (20, f"[{members[Membership.Slot.SON]} · 아들]"),
                (60, f"[{members[Membership.Slot.DAUGHTER]} · 딸]"),
            ))
            sys.stdout.flush()
        super().tearDownClass()

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner", password="Owner-Passphrase1!", display_name="정아", gender=User.Gender.FEMALE
        )
        self.member = User.objects.create_user(
            username="member", password="Member-Passphrase1!", display_name="선희", gender=User.Gender.FEMALE
        )
        self.owner_token = AccessToken.issue(self.owner)
        self.member_token = AccessToken.issue(self.member)

    def post(self, path, data, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(path, json.dumps(data), content_type="application/json", **headers)

    def create_room(self):
        response = self.post(
            "/api/families/create/",
            {"room_name": "정아네", "password": "roompass"},
            self.owner_token,
        )
        self.assertEqual(response.status_code, 201)
        return FamilyRoom.objects.get(pk=response.json()["room"]["id"])

    def test_create_uses_existing_account_and_current_updates_digest_time(self):
        self.assertEqual(self.post("/api/families/create/", {"room_name": "정아네", "password": "roompass"}).status_code, 401)
        room = self.create_room()
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(room.owner, self.owner)
        self.assertNotEqual(room.password_hash, "roompass")
        self.assertTrue(check_password("roompass", room.password_hash))
        self.assertTrue(Membership.objects.filter(room=room, user=self.owner, slot=Membership.Slot.OWNER).exists())

        current = self.client.get("/api/families/current/", HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["digest_time"], "21:00")
        updated = self.client.patch(
            "/api/families/current/", json.dumps({"digest_time": "19:30"}),
            content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.owner_token}"
        )
        self.assertEqual(updated.status_code, 200)
        room.refresh_from_db()
        self.assertEqual(room.digest_time, time(19, 30))
        print("Family create/current API test pass", flush=True)

    def test_lookup_checks_invitation_password(self):
        room = self.create_room()
        response = self.post(
            "/api/families/lookup/", {"invite_code": room.invite_code.lower(), "password": "roompass"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], room.pk)
        self.assertNotIn("password_hash", response.json())
        self.assertEqual(self.post(
            "/api/families/lookup/", {"invite_code": room.invite_code, "password": "wrong"}
        ).status_code, 403)
        print("Family lookup API test pass", flush=True)

    def test_join_uses_existing_account_and_rejects_occupied_slot(self):
        room = self.create_room()
        data = {"invite_code": room.invite_code, "password": "roompass", "slot": "grandma-mother"}
        joined = self.post("/api/families/join/", data, self.member_token)
        self.assertEqual(joined.status_code, 200)
        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(Membership.objects.filter(room=room, user=self.member, slot="grandma-mother").exists())
        owner = next(member for member in joined.json()["room"]["members"] if member["is_owner"])
        self.assertEqual(owner["relationship"], "손녀")
        self.assertEqual(self.post("/api/families/join/", data, self.member_token).status_code, 409)
        self.assertEqual(self.post("/api/families/join/", {**data, "slot": "father"}, self.member_token).status_code, 409)
        self.assertEqual(self.post("/api/families/join/", {**data, "slot": "invented"}, self.member_token).status_code, 400)
        self.assertEqual(Membership.objects.filter(room=room).count(), 2)

        father = User.objects.create_user(
            username="father", password="Father-Passphrase1!", display_name="병호", gender=User.Gender.MALE
        )
        father_token = AccessToken.issue(father)
        self.assertEqual(self.post(
            "/api/families/join/", {**data, "slot": "father"}, father_token
        ).status_code, 200)
        another_user = User.objects.create_user(
            username="another", password="Another-Passphrase1!", display_name="가족"
        )
        another_token = AccessToken.issue(another_user)
        self.assertEqual(self.post("/api/families/join/", data, another_token).status_code, 409)
        self.assertEqual(Membership.objects.filter(room=room).count(), 3)
        self.assertEqual(self.client.patch(
            "/api/families/current/", json.dumps({"digest_time": "18:00"}),
            content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.member_token}"
        ).status_code, 403)
        for username, name, gender, slot in (
            ("paternal_grandma", "경자", User.Gender.FEMALE, Membership.Slot.GRANDMA_FATHER),
            ("mother", "지현", User.Gender.FEMALE, Membership.Slot.MOTHER),
            ("son", "준호", User.Gender.MALE, Membership.Slot.SON),
            ("daughter", "수아", User.Gender.FEMALE, Membership.Slot.DAUGHTER),
        ):
            relative = User.objects.create_user(
                username=username, password="Relative-Passphrase1!", display_name=name, gender=gender
            )
            token = AccessToken.issue(relative)
            self.assertEqual(self.post(
                "/api/families/join/", {**data, "slot": slot}, token
            ).status_code, 200)
        self.assertEqual(Membership.objects.filter(room=room).count(), 7)
        type(self).family_tree_snapshot = (
            room.name,
            {
                membership.slot: membership.user.display_name
                for membership in room.members.select_related("user").order_by("joined_at", "pk")
            },
        )
        print("Family join API test pass", flush=True)

    def test_invalid_requests_and_missing_membership(self):
        self.assertEqual(self.client.get(
            "/api/families/current/", HTTP_AUTHORIZATION=f"Bearer {self.owner_token}"
        ).status_code, 403)
        self.assertEqual(self.post(
            "/api/families/create/", {"room_name": "", "password": "roompass"}, self.owner_token
        ).status_code, 400)
        self.assertEqual(self.post(
            "/api/families/create/", {"room_name": "정아네", "password": "roompass", "digest_time": "bad"},
            self.owner_token
        ).status_code, 400)
        self.assertEqual(FamilyRoom.objects.count(), 0)
        print("Family API validation test pass", flush=True)
