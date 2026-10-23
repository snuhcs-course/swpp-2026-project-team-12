import json
from datetime import time

from django.contrib.auth.hashers import check_password
from django.db.models import ProtectedError
from django.test import TestCase

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyPerson, FamilyRoom, Membership, ParentChild, Partnership
from apps.families.utils import relationship


class FamilyWorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", display_name="준하", gender="male")
        self.member = User.objects.create_user(username="member", display_name="구본재", gender="male")
        self.owner_token, self.member_token = AccessToken.issue(self.owner), AccessToken.issue(self.member)
        response = self.post("/api/families/create/", {"room_name": "준하네", "password": "roompass"}, self.owner_token)
        self.assertEqual(response.status_code, 201)
        self.room = FamilyRoom.objects.get(pk=response.json()["room"]["id"])
        self.invitation = {"invite_code": self.room.invite_code, "password": "roompass"}
        self.root = str(self.room.people.get().pk)

    def post(self, path, data, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(path, json.dumps(data), content_type="application/json", **headers)

    def join(self, additions, selected, version=0, token=None):
        return self.post("/api/families/join/", {**self.invitation, "tree_version": version,
                         "additions": additions, "person_id": selected}, token or self.member_token)

    def add(self, key, anchor, relation, co=None):
        value = {"id": "new_" + key, "anchor_id": anchor, "relation": relation}
        if co:
            value["co_parent_id"] = co
        return value

    def test_create_lookup_and_current(self):
        self.assertTrue(check_password("roompass", self.room.password_hash))
        self.assertEqual(self.room.digest_time, time(21))
        self.assertEqual(self.room.members.get().person_id, int(self.root))
        found = self.post("/api/families/lookup/", {**self.invitation, "invite_code": self.room.invite_code.lower()})
        self.assertEqual(found.status_code, 200)
        self.assertNotIn("password_hash", found.json())
        self.assertEqual(found.json()["tree"]["owner_id"], self.root)
        self.assertEqual(found.json()["tree"]["version"], 0)
        self.assertNotIn("slot", found.json()["members"][0])
        self.assertEqual(self.post("/api/families/lookup/", {**self.invitation, "password": "bad"}).status_code, 403)
        updated = self.client.patch("/api/families/current/", json.dumps({"digest_time": "19:30"}),
                                   content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        self.assertEqual(updated.status_code, 200)
        self.room.refresh_from_db()
        self.assertEqual(self.room.digest_time, time(19, 30))

    def test_expand_parent_sibling_nephew_through_blank_people(self):
        additions = [self.add("dad", self.root, "father"), self.add("mom", self.root, "mother"),
                     self.add("sibling", "new_dad", "child", "new_mom"),
                     self.add("nephew", "new_sibling", "child")]
        self.post("/api/families/lookup/", self.invitation)
        self.assertEqual(self.room.people.count(), 1)
        response = self.join(additions, "new_nephew")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(self.room.people.count(), 5)
        self.assertEqual(self.room.members.count(), 2)
        nephew = self.room.members.get(user=self.member).person
        sibling = nephew.parent_links.get().parent
        self.assertEqual(sibling.name, "")
        self.assertFalse(Membership.objects.filter(person=sibling).exists())
        self.assertEqual(set(sibling.parent_links.values_list("parent_id", flat=True)),
                         set(ParentChild.objects.filter(child_id=self.root).values_list("parent_id", flat=True)))
        self.assertEqual(relationship(self.owner, self.member, self.room), "조카")
        self.assertEqual(response.json()["room"]["tree"]["version"], 1)

    def test_claim_existing_blank_person_and_prevent_double_claim(self):
        self.assertEqual(self.join([self.add("child", self.root, "child"), self.add("grandchild", "new_child", "child")], "new_grandchild").status_code, 200)
        child = self.room.people.get(generation=-1)
        third = User.objects.create_user(username="third", display_name="수진", gender="female")
        self.assertEqual(self.join([], str(child.pk), version=1, token=AccessToken.issue(third)).status_code, 200)
        child.refresh_from_db()
        self.assertEqual(child.name, "수진")
        fourth = User.objects.create_user(username="fourth", display_name="다른 사람")
        self.assertEqual(self.join([], str(child.pk), version=2, token=AccessToken.issue(fourth)).status_code, 409)
        self.room.refresh_from_db()
        self.assertEqual(self.room.tree_version, 2)

    def test_stale_draft_does_not_partially_save(self):
        self.assertEqual(self.join([self.add("first", self.root, "child")], "new_first").status_code, 200)
        third = User.objects.create_user(username="third", display_name="다른 가족")
        response = self.join([self.add("stale", self.root, "child")], "new_stale", token=AccessToken.issue(third))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.room.people.count(), 2)
        self.assertEqual(self.room.members.count(), 2)
        self.room.refresh_from_db()
        self.assertEqual(self.room.tree_version, 1)

    def test_invalid_operations_roll_back_people_edges_and_revision(self):
        cases = [
            ([self.add("first", self.root, "child")], "missing"),
            ([self.add("first", self.root, "child"), self.add("first", self.root, "child")], "new_first"),
            ([self.add("a", self.root, "father"), self.add("b", self.root, "father")], "new_a"),
            ([self.add("a", self.root, "father"), self.add("b", self.root, "mother"), self.add("c", self.root, "parent")], "new_a"),
            ([self.add("a", self.root, "child"), self.add("b", "new_a", "child", self.root)], "new_a"),
            ([self.add("a", self.root, "child", self.root)], "new_a"),
            ([self.add("a", self.root, "sibling")], "new_a"),
            ([{"id": "new_a", "anchor_id": [], "relation": "child"}], "new_a"),
            ([None], "new_a"),
        ]
        for additions, selected in cases:
            with self.subTest(additions=additions):
                self.assertEqual(self.join(additions, selected).status_code, 400)
                self.assertEqual(self.room.people.count(), 1)
                self.assertEqual(ParentChild.objects.count(), 0)
                self.assertEqual(self.room.members.count(), 1)
                self.room.refresh_from_db()
                self.assertEqual(self.room.tree_version, 0)

    def test_other_room_people_cannot_be_claimed_or_connected(self):
        other = FamilyRoom.objects.create(name="other", owner=self.owner, invite_code="OTHER", password_hash="x")
        person = FamilyPerson.objects.create(room=other)
        self.assertEqual(self.join([], str(person.pk)).status_code, 400)
        self.assertEqual(self.join([self.add("a", str(person.pk), "child")], "new_a").status_code, 400)
        self.assertEqual(relationship(self.owner, self.owner, other), "가족")

    def test_spouse_and_joint_child(self):
        response = self.join([self.add("spouse", self.root, "spouse"), self.add("child", self.root, "child", "new_spouse")], "new_child")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Partnership.objects.count(), 1)
        self.assertEqual(self.room.members.get(user=self.member).person.parent_links.count(), 2)
        self.assertEqual(relationship(self.owner, self.member, self.room), "아들")

    def test_multiple_sons_have_distinct_people(self):
        self.assertEqual(self.join([self.add("a", self.root, "child")], "new_a").status_code, 200)
        second_son = User.objects.create_user(username="son2", display_name="둘째", gender="male")
        self.assertEqual(self.join([self.add("b", self.root, "child")], "new_b", version=1,
                                  token=AccessToken.issue(second_son)).status_code, 200)
        self.assertEqual(relationship(self.member, second_son, self.room), "형제자매")

    def test_join_accepts_200_additions_and_rejects_201_without_saving(self):
        additions = [self.add(f"child_{index}", self.root, "child") for index in range(201)]
        self.assertEqual(self.join(additions, "new_child_0").status_code, 400)
        self.assertEqual(self.room.people.count(), 1)
        self.room.refresh_from_db()
        self.assertEqual(self.room.tree_version, 0)
        self.assertEqual(self.join(additions[:200], "new_child_0").status_code, 200)
        self.assertEqual(self.room.people.count(), 201)

    def test_auth_validation_and_occupied_owner(self):
        self.assertEqual(self.post("/api/families/join/", self.invitation).status_code, 401)
        self.assertEqual(self.join([], self.root).status_code, 409)
        for version in (None, True, -1, "0"):
            self.assertEqual(self.join([], self.root, version=version).status_code, 400)
        self.assertEqual(self.join([], "new_absent").status_code, 400)
        self.assertEqual(self.join([self.add("mom", self.root, "mother")], "new_mom").status_code, 400)
        self.room.refresh_from_db()
        self.assertEqual(self.room.tree_version, 0)
        with self.assertRaises(ProtectedError):
            self.owner.delete()
