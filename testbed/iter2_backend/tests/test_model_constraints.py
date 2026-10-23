"""Database invariants owned by Django models and schema constraints."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.families.models import FamilyRoom, Membership


User = get_user_model()


class ModelConstraintTests(TestCase):
    def test_membership_user_and_slot_must_be_unique_per_room(self):
        owner = User.objects.create_user("owner", password="Valid-passphrase1!", display_name="Owner")
        son = User.objects.create_user("son", password="Valid-passphrase1!", display_name="Son")
        daughter = User.objects.create_user("daughter", password="Valid-passphrase1!", display_name="Daughter")
        room = FamilyRoom.objects.create(name="Constraint family", invite_code="MODEL01", password_hash="x", owner=owner)
        Membership.objects.create(room=room, user=owner, slot=Membership.Slot.OWNER)
        Membership.objects.create(room=room, user=son, slot=Membership.Slot.SON)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(room=room, user=son, slot=Membership.Slot.DAUGHTER)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(room=room, user=daughter, slot=Membership.Slot.SON)
