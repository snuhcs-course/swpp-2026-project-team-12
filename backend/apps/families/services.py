import secrets
from datetime import time

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction

from apps.api import APIError

from .models import FamilyPerson, FamilyRoom, Membership
from .utils.tree import tree_data
from .utils import relationship


def required_string(data, key, max_length):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise APIError("입력한 내용을 다시 확인해 주세요.")
    return value.strip()


def parse_time(value):
    try:
        result = time.fromisoformat(value)
        if result.second or result.microsecond or result.tzinfo:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise APIError("요약 받을 시간을 다시 확인해 주세요.") from None


def room_data(room, viewer=None):
    members = room.members.select_related("user", "person").order_by("joined_at", "pk")
    return {
        "id": room.pk,
        "name": room.name,
        "invite_code": room.invite_code,
        "owner_name": room.owner.display_name,
        "digest_time": room.digest_time.strftime("%H:%M"),
        "tree": tree_data(room),
        "members": [
            {
                "id": membership.user_id,
                "name": membership.user.display_name,
                "person_id": str(membership.person_id),
                "generation": membership.person.generation,
                "is_owner": membership.user_id == room.owner_id,
                "relationship": relationship(viewer or room.owner, membership.user, room),
            }
            for membership in members
        ],
    }


def invitation_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not FamilyRoom.objects.filter(invite_code=code).exists():
            return code


def require_no_membership(user):
    # Serialize room creation/joining for this account on databases with row locks.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    if Membership.objects.filter(user=user).exists():
        raise APIError("이미 가입한 가족 방이 있어요. 현재 가족 방을 이용해 주세요.", 409)


@transaction.atomic
def create_room(owner, room_name, password, digest_time):
    require_no_membership(owner)
    room = FamilyRoom.objects.create(
        name=room_name,
        invite_code=invitation_code(),
        password_hash=make_password(password),
        owner=owner,
        digest_time=digest_time,
    )
    person = FamilyPerson.objects.create(room=room, name=owner.display_name, gender=owner.gender)
    Membership.objects.create(room=room, user=owner, person=person)
    return room


def find_invitation(code, password):
    room = FamilyRoom.objects.select_related("owner").filter(invite_code=code.upper()).first()
    if room is None or not check_password(password, room.password_hash):
        raise APIError("초대코드나 가족 방 비밀번호가 맞지 않아요.", 403)
    return room
