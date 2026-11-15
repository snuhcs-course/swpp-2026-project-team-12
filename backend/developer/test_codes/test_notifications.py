import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom, Membership
from apps.notifications.models import PushDevice, PushNotification
from apps.notifications.services import SEOUL, InvalidDevice, dispatch_pending, queue_reminders
from apps.posts.daily_questions import ensure_today
from apps.posts.models import Post, QuestionAnswer
from apps.replies.models import Comment, VoiceDraft
from .family_fixtures import add_member, auth_headers, link_parent


class PushTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="push-owner", display_name="정아", gender="female")
        self.grandma = User.objects.create_user(username="push-grandma", display_name="경자", gender="female")
        self.other = User.objects.create_user(username="push-other", display_name="다른 가족")
        self.room = FamilyRoom.objects.create(name="가족", owner=self.owner, invite_code="PUSH01", password_hash="unused")
        add_member(self.room, self.owner)
        add_member(self.room, self.grandma)
        link_parent(self.room, self.grandma, self.owner, generations=2)
        self.owner_raw = AccessToken.issue(self.owner)
        self.grandma_raw = AccessToken.issue(self.grandma)
        self.other_raw = AccessToken.issue(self.other)
        self.owner_device = self.device(self.owner_raw)
        self.grandma_device = self.device(self.grandma_raw)
        self.other_device = self.device(self.other_raw)

    def device(self, raw):
        return PushDevice.objects.create(installation_id=uuid.uuid4(), token=str(uuid.uuid4()),
                                         session=AccessToken.from_raw(raw))

    def post(self, author=None):
        return Post.objects.create(room=self.room, author=author or self.owner, caption="가족 소식")

    def request_device(self, raw=None, method="put", **data):
        return getattr(self.client, method)("/api/notifications/device/", json.dumps(data),
            content_type="application/json", **(auth_headers(raw) if raw else {}))

    def test_registration_auth_validation_rotation_and_logout(self):
        data = dict(installation_id=str(self.owner_device.installation_id), token="rotated-fcm-token")
        self.assertEqual(self.request_device(**data).status_code, 401)
        self.assertEqual(self.request_device(self.owner_raw, installation_id="bad", token="x").status_code, 400)
        old = str(self.owner_device.binding)
        self.assertEqual(self.request_device(self.owner_raw, **data).json()["binding"], old)
        switched = self.request_device(self.grandma_raw, **data)
        self.assertEqual(switched.status_code, 200)
        self.assertNotEqual(switched.json()["binding"], old)
        self.request_device(self.owner_raw, method="delete", **data)
        self.assertTrue(PushDevice.objects.filter(pk=self.owner_device.pk).exists())
        self.client.post("/api/accounts/logout/", **auth_headers(self.grandma_raw))
        self.assertFalse(PushDevice.objects.filter(pk=self.owner_device.pk).exists())

    def test_post_only_reaches_other_members_with_viewer_relationship(self):
        post = self.post(author=self.grandma)
        item = PushNotification.objects.get()
        self.assertEqual(item.recipient, self.owner)
        self.assertEqual(item.post, post)
        self.assertEqual(item.title, "토닥이 · 새 소식")
        self.assertIn("할머니 경자님이 게시글을 올렸어요!", item.body)

    def test_comment_only_reaches_author_and_contains_preview(self):
        post = self.post()
        PushNotification.objects.all().delete()
        comment = Comment.objects.create(post=post, author=self.grandma, text="정아야, 예쁘구나!\n다음에 같이 가자.")
        item = PushNotification.objects.get()
        self.assertEqual(item.recipient, self.owner)
        self.assertEqual(item.title, "할머니 경자")
        self.assertEqual(item.body, "정아야, 예쁘구나! 다음에 같이 가자.")
        self.assertEqual(item.event_key, f"comment:{comment.pk}")
        Comment.objects.create(post=post, author=self.owner, text="고마워요")
        self.assertEqual(PushNotification.objects.count(), 1)

    def test_question_answer_only_first_save_and_question_comment(self):
        q = ensure_today(self.room)
        self.assertFalse(PushNotification.objects.exists())
        answer = QuestionAnswer.objects.create(question=q, author=self.grandma, text="산책")
        answer.text = "수정"; answer.save()
        item = PushNotification.objects.get()
        self.assertEqual(item.question, q)
        self.assertIn(q.post.caption, item.body)
        Comment.objects.create(post=q.post, author=self.owner, text="같이 가요!")
        comment_push = PushNotification.objects.get(kind="question_comment")
        self.assertEqual(comment_push.recipient, self.grandma)
        self.assertIn("같이 가요!", comment_push.body)
        self.assertIn(q.post.caption, comment_push.body)

    def test_voice_confirmation_is_idempotent_and_draft_is_silent(self):
        post = self.post()
        PushNotification.objects.all().delete()
        draft = VoiceDraft.objects.create(post=post, author=self.grandma, recognized="잘 지내", converted="잘 지내니?")
        self.assertFalse(PushNotification.objects.exists())
        for _ in range(2):
            response = self.client.post(f"/api/replies/{draft.pk}/send/", **auth_headers(self.grandma_raw))
            self.assertEqual(response.status_code, 200)
        self.assertEqual(PushNotification.objects.count(), 1)

    def test_rollback_never_leaves_a_sendable_notification(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.post()
            raise RuntimeError("abort")
        self.assertFalse(PushNotification.objects.exists())

    def test_20_korea_only_unanswered_once_and_no_catchup_after_midnight(self):
        now = datetime(2026, 11, 14, 20, tzinfo=SEOUL)
        q = ensure_today(self.room, day=now.date())
        QuestionAnswer.objects.create(question=q, author=self.owner, text="완료")
        PushNotification.objects.all().delete()
        queue_reminders(now - timedelta(minutes=1))
        self.assertFalse(PushNotification.objects.exists())
        queue_reminders(now.astimezone(timezone.get_fixed_timezone(0)))
        queue_reminders(now + timedelta(minutes=20))
        item = PushNotification.objects.get()
        self.assertEqual(item.recipient, self.grandma)
        self.assertEqual(item.kind, "reminder")
        self.assertEqual(timezone.localtime(item.expires_at, SEOUL).hour, 0)
        queue_reminders(now + timedelta(hours=4))
        self.assertEqual(PushNotification.objects.count(), 1)

    def test_reminder_cancelled_if_answered_before_dispatch(self):
        now = timezone.localtime(timezone.now(), SEOUL).replace(hour=20, minute=0)
        q = ensure_today(self.room, day=now.date())
        queue_reminders(now)
        QuestionAnswer.objects.create(question=q, author=self.grandma, text="이제 답했어요")
        send = Mock()
        dispatch_pending(send)
        cancelled = PushNotification.objects.get(kind="reminder", recipient=self.grandma)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertFalse(any(call.args[0].pk == cancelled.pk for call in send.call_args_list))

    def test_worker_retry_and_no_resend_after_success(self):
        self.post()
        send = Mock(side_effect=RuntimeError("network down"))
        with self.assertLogs("apps.notifications.services", level="ERROR"):
            dispatch_pending(send)
        item = PushNotification.objects.get()
        self.assertEqual(item.status, "pending")
        self.assertEqual(item.attempts, 1)
        dispatch_pending(send)
        self.assertEqual(send.call_count, 1)
        PushNotification.objects.update(due_at=timezone.now() - timedelta(seconds=1))
        send.side_effect = None
        dispatch_pending(send); dispatch_pending(send)
        item.refresh_from_db()
        self.assertEqual(item.status, "sent")
        self.assertEqual(send.call_count, 2)

    def test_worker_cancels_old_binding_expired_sessions_and_left_room(self):
        self.post()
        self.grandma_device.binding = uuid.uuid4(); self.grandma_device.save()
        send = Mock(); dispatch_pending(send); send.assert_not_called()
        self.assertEqual(PushNotification.objects.get().status, "cancelled")
        self.post()
        Membership.objects.filter(room=self.room, user=self.grandma).delete()
        dispatch_pending(send); send.assert_not_called()

    def test_expired_token_and_inactive_account_do_not_receive(self):
        AccessToken.objects.filter(pk=self.grandma_device.session_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.post()
        self.assertFalse(PushNotification.objects.exists())
        AccessToken.objects.filter(pk=self.grandma_device.session_id).update(expires_at=timezone.now() + timedelta(days=1))
        self.grandma.is_active = False; self.grandma.save()
        self.post()
        self.assertFalse(PushNotification.objects.exists())

    def test_unregistered_device_is_removed_and_long_preview_is_bounded(self):
        post = self.post()
        PushNotification.objects.all().delete()
        Comment.objects.create(post=post, author=self.grandma, text="아" * 2000)
        self.assertEqual(len(PushNotification.objects.get().body), 180)
        dispatch_pending(Mock(side_effect=InvalidDevice()))
        self.assertFalse(PushDevice.objects.filter(pk=self.owner_device.pk).exists())

    def test_crashed_worker_lease_is_recovered(self):
        self.post()
        PushNotification.objects.update(status="sending", claimed_at=timezone.now() - timedelta(minutes=6))
        send = Mock(); dispatch_pending(send)
        send.assert_called_once()
        self.assertEqual(PushNotification.objects.get().status, "sent")

    def test_two_devices_receive_independently(self):
        self.device(self.grandma_raw)
        self.post()
        self.assertEqual(PushNotification.objects.count(), 2)
        send = Mock(); dispatch_pending(send)
        self.assertEqual(send.call_count, 2)

    def test_firebase_sdk_payload_is_private_data_with_bounded_size(self):
        from apps.notifications.services import firebase_send
        from firebase_admin import messaging
        self.post()
        item = PushNotification.objects.get()
        with patch("firebase_admin.get_app", return_value=Mock()), patch.object(messaging, "send") as send:
            firebase_send(item)
        message = send.call_args.args[0]
        self.assertIsInstance(message, messaging.Message)
        self.assertIsNone(message.notification)
        self.assertEqual(message.android.priority, "high")
        self.assertEqual(message.data["binding"], str(item.binding))
        self.assertEqual(message.data["post_id"], str(item.post_id))
        self.assertLess(len(json.dumps(message.data, ensure_ascii=False).encode()), 4096)
