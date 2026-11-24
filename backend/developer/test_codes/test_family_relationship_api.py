"""Relationship labels stay consistent across the APIs and queued notifications."""

import uuid

from django.test import TestCase

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyPerson, FamilyRoom, ParentChild, Partnership
from apps.notifications.models import PushDevice, PushNotification
from apps.posts.daily_questions import ensure_today
from apps.posts.models import Post, QuestionAnswer
from apps.replies.models import Comment

from .family_fixtures import add_member, auth_headers


class FamilyRelationshipAPITests(TestCase):
    def test_compact_labels_reach_every_surface_and_update_with_partnerships(self):
        users = {key: User.objects.create_user(username=key, display_name=name, gender=gender)
                 for key, name, gender in (
                     ("hyunwoo", "현우", "male"), ("jimin", "지민", "female"), ("sunhee", "선희", "female"))}
        room = FamilyRoom.objects.create(owner=users["hyunwoo"], name="가족", invite_code="LABELS", password_hash="unused")
        people = {key: add_member(room, user).person for key, user in users.items()}
        people["son"] = FamilyPerson.objects.create(room=room, gender="male")
        people["mother"] = FamilyPerson.objects.create(room=room, gender="female")
        for parent, child in (("hyunwoo", "son"), ("jimin", "son"), ("mother", "jimin"), ("sunhee", "mother")):
            ParentChild.objects.create(parent=people[parent], child=people[child])
        token = AccessToken.issue(users["hyunwoo"])
        headers = auth_headers(token, room)
        reverse_headers = auth_headers(AccessToken.issue(users["jimin"]), room)
        PushDevice.objects.create(installation_id=uuid.uuid4(), token="test-device", session=AccessToken.from_raw(token))
        question = ensure_today(room)
        QuestionAnswer.objects.create(question=question, author=users["jimin"], text="같이 산책해요")
        Comment.objects.create(post=question.post, author=users["sunhee"], text="좋아요")

        for partnered, partner_label, ancestor_label, reverse_label in (
            (False, "공동 부모", "공동 부모의 외할머니", "공동 부모"),
            (True, "아내", "아내의 외할머니", "남편"),
        ):
            with self.subTest(partnered=partnered):
                if partnered:
                    Partnership.objects.create(first_id=min(people["hyunwoo"].pk, people["jimin"].pk),
                                               second_id=max(people["hyunwoo"].pk, people["jimin"].pk))
                current = self.client.get("/api/families/current/", **headers)
                self.assertEqual(current.status_code, 200)
                labels = {member["id"]: member["relationship"] for member in current.json()["members"]}
                self.assertEqual(labels[users["jimin"].pk], partner_label)
                self.assertEqual(labels[users["sunhee"].pk], ancestor_label)
                reverse = self.client.get("/api/families/current/", **reverse_headers)
                self.assertEqual(reverse.status_code, 200)
                self.assertEqual(next(member["relationship"] for member in reverse.json()["members"]
                                      if member["id"] == users["hyunwoo"].pk), reverse_label)

                post = Post.objects.create(room=room, author=users["sunhee"], caption="가족 소식")
                Comment.objects.create(post=post, author=users["jimin"], text="반가워요")
                detail = self.client.get(f"/api/posts/{post.pk}/", **headers)
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.json()["relationship"], ancestor_label)
                self.assertEqual(detail.json()["comments"][0]["relationship"], partner_label)
                feed = self.client.get("/api/posts/", **headers)
                self.assertEqual(feed.status_code, 200)
                self.assertEqual(next(item["relationship"] for item in feed.json()["posts"]
                                      if item["id"] == post.pk), ancestor_label)

                answers = self.client.get(f"/api/daily-questions/{question.pk}/", **headers)
                self.assertEqual(answers.status_code, 200)
                self.assertEqual(answers.json()["answers"][0]["relationship"], partner_label)
                self.assertEqual(answers.json()["comments"][0]["relationship"], ancestor_label)
                notice = PushNotification.objects.get(post=post, kind="post")
                self.assertEqual(notice.body, f"{ancestor_label} 선희님이 게시글을 올렸어요!")
                self.assertEqual(Partnership.objects.count(), int(partnered))
