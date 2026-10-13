from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from integrations.ai import provider

from .models import Digest


def cutoff(room, date):
    """Return the room's scheduled digest boundary in the configured time zone."""
    return timezone.make_aware(datetime.combine(date, room.digest_time))


def generate_digest(room, date, retry=False):
    """Generate one cached digest for a room and day after its cutoff."""
    end = cutoff(room, date)
    now = timezone.now()
    if end > now:
        return None

    obj, _ = Digest.objects.get_or_create(room=room, date=date)
    reclaim_before = now - timedelta(minutes=2)
    # A later time can include posts that arrived after an earlier empty result.
    # Keep completed summaries and historical windows unchanged.
    extend_empty = (
        date == timezone.localtime(now).date()
        and obj.status == "empty"
        and obj.window_end is not None
        and obj.window_end < end
    )
    if obj.status == "processing" and obj.updated_at >= reclaim_before:
        return obj
    if (
        obj.status not in {"pending", "processing"}
        and not extend_empty
        and not (retry and obj.status == "failed")
    ):
        return obj

    eligible = Q(status="pending") | Q(status="processing", updated_at__lt=reclaim_before)
    if extend_empty:
        eligible |= Q(status="empty", window_end__lt=end)
    if retry:
        eligible |= Q(status="failed")
    claimed = Digest.objects.filter(pk=obj.pk).filter(eligible).update(status="processing", updated_at=now)
    if not claimed:
        obj.refresh_from_db()
        return obj

    previous = room.digests.filter(date=date - timedelta(days=1), window_end__isnull=False).first()
    start = obj.window_start or (previous.window_end if previous else cutoff(room, date - timedelta(days=1)))
    end = end if extend_empty else obj.window_end or end
    posts = list(
        room.posts.filter(created_at__gte=start, created_at__lt=end)
        .select_related("author")
        .order_by("created_at")
    )
    obj.window_start, obj.window_end = start, end
    obj.posts.set(posts)
    if not posts:
        obj.status, obj.text = "empty", ""
    else:
        try:
            obj.text, obj.status = provider.summarize(posts), "ready"
        except provider.AIUnavailable:
            obj.status = "failed"
    obj.save()
    return obj
