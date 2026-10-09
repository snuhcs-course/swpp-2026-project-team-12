from datetime import date, timedelta

from django.utils import timezone

from apps.api import APIError, api, body
from apps.posts.services import current_room, serialize

from .services import generate_digest


@api("GET", "POST")
def daily(request):
    room = current_room(request)
    requested = request.GET.get("date") if request.method == "GET" else body(request).get("date")
    try:
        chosen = timezone.localdate() if requested in (None, "") else date.fromisoformat(requested)
        if requested not in (None, "") and (requested != chosen.isoformat() or chosen == date.min):
            raise ValueError("Use YYYY-MM-DD after 0001-01-01.")
    except (TypeError, ValueError) as error:
        raise APIError("날짜를 다시 확인해 주세요.") from error
    digest = generate_digest(room, chosen, retry=request.method == "POST")
    return {
        "date": chosen.isoformat(),
        "status": digest.status if digest else "pending",
        "text": digest.text if digest else "",
        "digest_time": room.digest_time.strftime("%H:%M"),
        "posts": [serialize(post, request) for post in digest.posts.select_related("author")]
        if digest else [],
    }


@api("GET")
def history(request):
    room = current_room(request)
    dates = {timezone.localdate()}
    for created_at in room.posts.values_list("created_at", flat=True)[:200]:
        local = timezone.localtime(created_at)
        dates.add(local.date() + (timedelta(days=1) if local.time() >= room.digest_time else timedelta()))
    dates.update(room.digests.values_list("date", flat=True))
    return {"dates": [day.isoformat() for day in sorted(dates, reverse=True)]}
