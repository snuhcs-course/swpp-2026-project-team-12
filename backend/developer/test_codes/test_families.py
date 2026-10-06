from datetime import time

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from apps.accounts.models import User
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
