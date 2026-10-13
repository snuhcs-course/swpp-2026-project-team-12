from django.http import JsonResponse

from apps.api import APIError, api, body

from .models import Membership
from .services import create_room, find_invitation, join_room, parse_time, required_string, room_data


@api("POST")
def create(request):
    data = body(request)
    room = create_room(
        request.user,
        required_string(data, "room_name", 60),
        required_string(data, "password", 128),
        parse_time(data.get("digest_time", "21:00")),
    )
    return JsonResponse({"room": room_data(room, request.user)}, status=201)


@api("POST", anonymous=True)
def lookup(request):
    data = body(request)
    room = find_invitation(
        required_string(data, "invite_code", 8),
        required_string(data, "password", 128),
    )
    return room_data(room)


@api("POST")
def join(request):
    data = body(request)
    room = find_invitation(
        required_string(data, "invite_code", 8),
        required_string(data, "password", 128),
    )
    join_room(room, request.user, required_string(data, "slot", 30))
    return {"room": room_data(room, request.user)}


@api("GET", "PATCH")
def current(request):
    membership = Membership.objects.select_related("room", "room__owner").filter(
        user=request.user
    ).order_by("joined_at", "pk").first()
    if membership is None:
        raise APIError("가족 방에 먼저 들어가 주세요.", 403)
    room = membership.room
    if request.method == "PATCH":
        if room.owner_id != request.user.pk:
            raise APIError("가족 방을 만든 사람이 시간을 바꿀 수 있어요.", 403)
        room.digest_time = parse_time(body(request).get("digest_time"))
        room.save(update_fields=["digest_time"])
    return room_data(room, request.user)
