import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import Post
from apps.replies.models import Comment

from .test_posts import sample_image


class CommentAPITests(TestCase):
    def setUp(self):
        test_media = Path(settings.BASE_DIR) / "developer" / "test_media"
        test_media.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=test_media)
        self.addCleanup(temporary.cleanup)
        configured = override_settings(MEDIA_ROOT=temporary.name)
        configured.enable()
        self.addCleanup(configured.disable)

        self.owner = User.objects.create_user(
            username="owner", password="Owner-Passphrase1!",
            display_name="정아", gender=User.Gender.FEMALE,
        )
        self.grandma = User.objects.create_user(
            username="paternal_grandma", password="Relative-Passphrase1!",
            display_name="경자", gender=User.Gender.FEMALE,
        )
        self.outsider = User.objects.create_user(
            username="outsider", password="Outsider-Passphrase1!", display_name="외부인"
        )
        self.room = FamilyRoom.objects.create(
            name="정아네", invite_code="ROOM01", password_hash="hashed", owner=self.owner
        )
        other_room = FamilyRoom.objects.create(
            name="다른 가족", invite_code="ROOM02", password_hash="hashed", owner=self.outsider
        )
        Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.OWNER)
        Membership.objects.create(room=self.room, user=self.grandma, slot=Membership.Slot.GRANDMA_FATHER)
        Membership.objects.create(room=other_room, user=self.outsider, slot=Membership.Slot.OWNER)
        self.owner_token = AccessToken.issue(self.owner)
        self.grandma_token = AccessToken.issue(self.grandma)
        self.outsider_token = AccessToken.issue(self.outsider)
        uploaded = self.client.post(
            "/api/posts/",
            {"image": sample_image(), "caption": "포챔스에서 독개굴 이로치 잡았다~ 간지 ㅁㅌㅊ?"},
            **self.auth(self.owner_token),
        )
        self.assertEqual(uploaded.status_code, 200)
        self.post = Post.objects.get(pk=uploaded.json()["id"])

    @staticmethod
    def auth(token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def comment(self, text, token=None):
        return self.client.post(
            f"/api/posts/{self.post.pk}/comments/",
            json.dumps({"text": text}), content_type="application/json",
            **self.auth(token or self.grandma_token),
        )

    def test_comment_appears_in_post_detail_and_feed(self):
        response = self.comment("  정아야, 정말 멋지구나!  ")
        self.assertEqual(response.status_code, 200)
        comment = Comment.objects.get(pk=response.json()["id"])
        self.assertEqual(comment.text, "정아야, 정말 멋지구나!")
        self.assertEqual(comment.author, self.grandma)
        self.assertEqual(comment.source, "text")
        self.assertEqual(comment.post, self.post)

        detail = self.client.get(f"/api/posts/{self.post.pk}/", **self.auth(self.owner_token)).json()
        self.assertEqual(detail["comment_count"], 1)
        self.assertEqual(detail["comments"][0]["text"], comment.text)
        self.assertEqual(detail["comments"][0]["author_name"], "경자")
        self.assertEqual(detail["comments"][0]["relationship"], "할머니")
        self.assertEqual(detail["comments"][0]["source"], "text")
        self.assertIn("created_at", detail["comments"][0])
        feed = self.client.get("/api/posts/", **self.auth(self.owner_token)).json()
        self.assertEqual(feed["posts"][0]["comment_count"], 1)
        print("Comment DB, post detail, and feed test pass", flush=True)

    def test_comments_reject_invalid_input_and_other_rooms(self):
        path = f"/api/posts/{self.post.pk}/comments/"
        self.assertEqual(self.client.post(path).status_code, 401)
        self.assertEqual(self.comment("안녕", self.outsider_token).status_code, 404)
        self.assertEqual(self.client.post(
            path, {"text": "안녕"}, **self.auth(self.grandma_token)
        ).status_code, 415)
        for text in (" ", "가" * 2001, 42):
            self.assertEqual(self.comment(text).status_code, 400)
        self.assertEqual(self.client.post(
            "/api/posts/999999/comments/", json.dumps({"text": "안녕"}),
            content_type="application/json", **self.auth(self.grandma_token),
        ).status_code, 404)
        self.assertFalse(Comment.objects.exists())
        print("Comment validation and room isolation test pass", flush=True)
