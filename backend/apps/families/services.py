import secrets
from datetime import time

from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction

from apps.api import APIError

from .models import FamilyRoom, Membership


SLOTS = {
    "father": ("아버지", 1, "male"),
    "mother": ("어머니", 1, "female"),
    "grandma-father": ("할머니", 2, "female"),
    "grandma-mother": ("외할머니", 2, "female"),
    "son": ("아들", -1, "male"),
    "daughter": ("딸", -1, "female"),
    "grandson": ("손자", -2, "male"),
    "granddaughter": ("손녀", -2, "female"),
}


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


def relationship(viewer, target, room):
    if viewer.pk == target.pk:
        return "나"
    viewer_member = room.members.filter(user=viewer).first()
    target_member = room.members.filter(user=target).first()
    if not viewer_member or not target_member:
        return "가족"
    if viewer_member.slot == Membership.Slot.OWNER:
        return SLOTS.get(target_member.slot, ("가족",))[0]
    if target_member.slot == Membership.Slot.OWNER:
        generation = SLOTS.get(viewer_member.slot, ("", 0))[1]
        reverse = {
            2: {"female": "손녀", "male": "손자", "unknown": "손주"},
            1: {"female": "딸", "male": "아들", "unknown": "자녀"},
            -1: {"female": "어머니", "male": "아버지", "unknown": "부모"},
            -2: {"female": "할머니", "male": "할아버지", "unknown": "조부모"},
        }
        return reverse.get(generation, {}).get(target.gender, "가족")
    special = {
        ("grandma-father", "father"): "아들",
        ("grandma-father", "mother"): "며느리",
        ("grandma-mother", "mother"): "딸",
        ("grandma-mother", "father"): "사위",
    }
    return special.get((viewer_member.slot, target_member.slot), "가족")


def room_data(room, viewer=None):
    members = room.members.select_related("user").order_by("joined_at", "pk")
    return {
        "id": room.pk,
        "name": room.name,
        "invite_code": room.invite_code,
        "owner_name": room.owner.display_name,
        "digest_time": room.digest_time.strftime("%H:%M"),
        "members": [
            {
                "id": membership.user_id,
                "name": membership.user.display_name,
                "slot": membership.slot,
                "generation": SLOTS.get(membership.slot, ("", 0))[1],
                "is_owner": membership.user_id == room.owner_id,
                "relationship": relationship(viewer, membership.user, room)
                if viewer else SLOTS.get(membership.slot, ("",))[0],
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


@transaction.atomic
def create_room(owner, room_name, password, digest_time):
    room = FamilyRoom.objects.create(
        name=room_name,
        invite_code=invitation_code(),
        password_hash=make_password(password),
        owner=owner,
        digest_time=digest_time,
    )
    Membership.objects.create(room=room, user=owner, slot=Membership.Slot.OWNER)
    return room


def find_invitation(code, password):
    room = FamilyRoom.objects.select_related("owner").filter(invite_code=code.upper()).first()
    if room is None or not check_password(password, room.password_hash):
        raise APIError("초대코드나 가족 방 비밀번호가 맞지 않아요.", 403)
    return room


def join_room(room, user, slot):
    if slot not in SLOTS:
        raise APIError("가족에서 내 자리를 선택해 주세요.")
    try:
        with transaction.atomic():
            if room.members.filter(user=user).exists():
                raise APIError("이미 가입한 가족 방이에요.", 409)
            if room.members.filter(slot=slot).exists():
                raise APIError("이미 가입한 가족의 자리예요.", 409)
            Membership.objects.create(room=room, user=user, slot=slot)
    except IntegrityError as error:
        raise APIError("이미 가입한 가족의 자리예요.", 409) from error
    return room
