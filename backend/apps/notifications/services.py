from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from apps.families.models import FamilyRoom, Membership
from apps.families.utils import relationship
from apps.posts.models import QuestionAnswer
from .models import PushDevice, PushNotification

SEOUL = ZoneInfo("Asia/Seoul")


def preview(text, limit=180):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def actor_label(viewer, actor, room):
    relation = relationship(viewer, actor, room)
    name = actor.display_name
    return name if relation == name else f"{relation} {name}"


def enqueue(*, room, post, actor, key, kind, question=None, text="", recipient_id=None):
    now = timezone.now()
    devices = PushDevice.objects.select_related("session__user").filter(
        session__expires_at__gt=now, session__user__is_active=True,
        session__user__memberships__room=room,
    )
    if actor:
        devices = devices.exclude(session__user=actor)
    if recipient_id is not None:
        devices = devices.filter(session__user_id=recipient_id)
    expires = now + timedelta(days=1)
    if kind == "reminder":
        expires = datetime.combine(question.date + timedelta(days=1), time.min, tzinfo=SEOUL)
    for device in devices:
        user = device.session.user
        label = actor_label(user, actor, room) if actor else "토닥이"
        if kind == "post":
            title, body = "토닥이 · 새 소식", f"{label}님이 게시글을 올렸어요!"
        elif kind == "comment":
            title, body = label, preview(text)
        elif kind == "answer":
            title, body = label, f"오늘의 질문에 답했어요!\nQ. {preview(question.post.caption)}"
        elif kind == "question_comment":
            title, body = label, f"{preview(text, 140)}\nQ. {preview(question.post.caption)}"
        else:
            title, body = "토닥이 · 오늘의 질문", f"아직 오늘의 이야기를 들려주지 않으셨어요 💛\nQ. {preview(question.post.caption)}"
        PushNotification.objects.get_or_create(device=device, event_key=key, defaults={
            "binding": device.binding, "recipient": user, "room": room, "post": post,
            "question": question, "kind": kind, "title": title, "body": body,
            "expires_at": expires,
        })


def queue_reminders(now=None):
    now = timezone.localtime(now or timezone.now(), SEOUL)
    if now.hour != 20:
        return
    from apps.posts.daily_questions import ensure_today
    rooms = FamilyRoom.objects.filter(members__user_id__in=PushDevice.objects.filter(
        session__expires_at__gt=now).values("session__user_id")).distinct()
    for room in rooms:
        question = ensure_today(room, day=now.date())
        answered = question.answers.values("author_id")
        for member in room.members.exclude(user_id__in=answered):
            enqueue(room=room, post=question.post, actor=None,
                    key=f"reminder:{question.pk}:{member.user_id}", kind="reminder", question=question,
                    recipient_id=member.user_id)


def is_eligible(item, now):
    device = item.device
    return (item.expires_at > now and device.binding == item.binding
            and device.session.user_id == item.recipient_id and device.session.expires_at > now
            and device.session.user.is_active
            and Membership.objects.filter(room_id=item.room_id, user_id=item.recipient_id).exists()
            and not (item.kind == "reminder" and QuestionAnswer.objects.filter(
                question_id=item.question_id, author_id=item.recipient_id).exists()))


def dispatch_pending(send, limit=100):
    """CAS claims also work on SQLite; a stopped worker's lease expires after 5m."""
    now = timezone.now()
    query = PushNotification.objects.filter(due_at__lte=now).filter(
        Q(status="pending") | Q(status="sending", claimed_at__lt=now - timedelta(minutes=5)))
    ids = list(query.order_by("id").values_list("id", flat=True)[:limit])
    for pk in ids:
        if not query.filter(pk=pk).update(status="sending", claimed_at=now):
            continue
        item = PushNotification.objects.select_related("device__session__user").filter(pk=pk).first()
        if item is None:
            continue
        if not is_eligible(item, now):
            PushNotification.objects.filter(pk=pk).update(status="cancelled")
            continue
        try:
            send(item)
        except InvalidDevice:
            # A concurrently refreshed/reassigned token must survive an old send.
            PushDevice.objects.filter(pk=item.device_id, token=item.device.token, binding=item.binding).delete()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Push delivery %s failed", pk)
            attempts = item.attempts + 1
            PushNotification.objects.filter(pk=pk, claimed_at=now).update(
                status="failed" if attempts >= 8 else "pending", attempts=attempts,
                due_at=now + timedelta(seconds=min(3600, 30 * 2 ** attempts)))
        else:
            PushNotification.objects.filter(pk=pk, claimed_at=now).update(status="sent")


class InvalidDevice(Exception):
    pass


def firebase_send(item):
    import firebase_admin
    from firebase_admin import messaging
    try:
        app = firebase_admin.get_app()
    except ValueError:
        app = firebase_admin.initialize_app(options={"httpTimeout": 20})
    data = {"event_id": str(item.pk), "binding": str(item.binding), "user_id": str(item.recipient_id),
            "room_id": str(item.room_id), "post_id": str(item.post_id),
            "question_id": str(item.question_id or ""), "kind": item.kind,
            "title": item.title, "body": item.body}
    try:
        messaging.send(messaging.Message(token=item.device.token, data=data,
            android=messaging.AndroidConfig(priority="high", ttl=item.expires_at - timezone.now())), app=app)
    except messaging.UnregisteredError as error:
        raise InvalidDevice from error
