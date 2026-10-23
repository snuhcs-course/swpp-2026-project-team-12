"""Database invariants owned by Django models and schema constraints."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.families.models import FamilyPerson, FamilyRoom, Membership
from developer.test_codes.family_fixtures import add_member


User = get_user_model()


class ModelConstraintTests(TestCase):
    def test_membership_user_and_person_must_be_unique_per_room(self):
        owner = User.objects.create_user("owner", password="Valid-passphrase1!", display_name="Owner")
        son = User.objects.create_user("son", password="Valid-passphrase1!", display_name="Son")
        daughter = User.objects.create_user("daughter", password="Valid-passphrase1!", display_name="Daughter")
        room = FamilyRoom.objects.create(name="Constraint family", invite_code="MODEL01", password_hash="x", owner=owner)
        add_member(room, owner)
        son_membership = add_member(room, son, -1)
        other_person = FamilyPerson.objects.create(room=room, generation=-1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(room=room, user=son, person=other_person)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(room=room, user=daughter, person=son_membership.person)
