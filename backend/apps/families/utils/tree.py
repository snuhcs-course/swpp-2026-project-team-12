"""Account-independent family people and atomic, append-only invitation drafts."""

import re

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F

from apps.api import APIError
from ..models import FamilyPerson, FamilyRoom, Membership, ParentChild, Partnership


CONFLICT = "가계도가 변경되었거나 선택한 자리에 다른 가족이 가입했어요. 최신 가계도에서 다시 진행해 주세요."
MAX_ADDITIONS = 200


def tree_data(room):
    version = FamilyRoom.objects.values_list("tree_version", flat=True).get(pk=room.pk)
    members = {m.person_id: m for m in room.members.select_related("user")}
    people = []
    owner_id = None
    for person in room.people.order_by("pk"):
        member = members.get(person.pk)
        is_owner = bool(member and member.user_id == room.owner_id)
        if is_owner:
            owner_id = str(person.pk)
        people.append({
            "id": str(person.pk), "name": member.user.display_name if member else person.name,
            "gender": person.gender, "generation": person.generation,
            "user_id": member.user_id if member else None, "is_owner": is_owner,
        })
    return {
        "version": version, "owner_id": owner_id, "people": people,
        "parents": [{"parent_id": str(p), "child_id": str(c)} for p, c in
                    ParentChild.objects.filter(parent__room=room).values_list("parent_id", "child_id")],
        "partnerships": [{"first_id": str(a), "second_id": str(b)} for a, b in
                         Partnership.objects.filter(first__room=room).values_list("first_id", "second_id")],
    }


def join_tree(room, user, data):
    version, additions, selected = data.get("tree_version"), data.get("additions", []), data.get("person_id")
    if type(version) is not int or version < 0:
        raise APIError("가계도를 다시 불러와 주세요.")
    if not isinstance(additions, list) or len(additions) > MAX_ADDITIONS:
        raise APIError("한 번에 추가할 수 있는 가족은 200명까지예요.")
    if not isinstance(selected, str) or not selected or len(selected) > 80:
        raise APIError("가계도에서 내 자리를 선택해 주세요.")
    if Membership.objects.filter(room=room, user=user).exists():
        raise APIError("이미 참여한 가족 방이에요.", 409)
    try:
        with transaction.atomic():
            # A conditional UPDATE is also a write lock on SQLite, where
            # select_for_update alone does not serialize competing joins.
            changed = FamilyRoom.objects.filter(pk=room.pk, tree_version=version).update(tree_version=F("tree_version") + 1)
            if not changed:
                raise APIError(CONFLICT, 409)
            people = {str(p.pk): p for p in room.people.all()}
            for addition in additions:
                add_person(people, room, addition)
            person = people.get(selected)
            if person is None:
                raise APIError("가계도에서 내 자리를 선택해 주세요.")
            if Membership.objects.filter(person=person).exists():
                raise APIError(CONFLICT, 409)
            if person.gender != "unknown" and user.gender != "unknown" and person.gender != user.gender:
                raise APIError("선택한 자리와 계정의 성별이 달라요. 내 자리를 다시 확인해 주세요.")
            person.name = user.display_name
            if user.gender != "unknown":
                person.gender = user.gender
            person.save(update_fields=["name", "gender"])
            Membership.objects.create(room=room, user=user, person=person)
    except IntegrityError as error:
        raise APIError(CONFLICT, 409) from error
    except OperationalError as error:
        if "locked" not in str(error).lower():
            raise
        raise APIError(CONFLICT, 409) from error


def add_person(people, room, addition):
    if not isinstance(addition, dict):
        raise APIError("추가할 가족 정보를 다시 확인해 주세요.")
    key, anchor_key, relation = addition.get("id"), addition.get("anchor_id"), addition.get("relation")
    if not isinstance(key, str) or not re.fullmatch(r"new_[a-zA-Z0-9_-]{1,70}", key) or key in people:
        raise APIError("추가할 가족의 번호가 올바르지 않아요.")
    if not isinstance(anchor_key, str) or anchor_key not in people:
        raise APIError("연결할 가족을 다시 선택해 주세요.")
    if relation not in ("father", "mother", "parent", "spouse", "child"):
        raise APIError("추가할 관계를 다시 선택해 주세요.")
    anchor = people[anchor_key]
    co_key = addition.get("co_parent_id")
    if co_key is not None and (relation != "child" or not isinstance(co_key, str) or co_key not in people or co_key == anchor_key):
        raise APIError("함께 연결할 부모를 다시 확인해 주세요.")
    co_parent = people.get(co_key)
    if co_parent:
        partnered = Partnership.objects.filter(first_id=min(anchor.pk, co_parent.pk), second_id=max(anchor.pk, co_parent.pk)).exists()
        shared_child = ParentChild.objects.filter(parent=anchor, child__parent_links__parent=co_parent).exists()
        if co_parent.generation != anchor.generation or not (partnered or shared_child):
            raise APIError("배우자 또는 기존 공동 부모만 함께 연결할 수 있어요.")
    gender = {"father": "male", "mother": "female"}.get(relation, "unknown")
    if relation in ("father", "mother", "parent"):
        parents = list(FamilyPerson.objects.filter(child_links__child=anchor))
        if len(parents) >= 2 or (gender != "unknown" and any(p.gender == gender for p in parents)):
            raise APIError("이미 등록된 부모 자리예요.")
    generation = anchor.generation + (1 if relation in ("father", "mother", "parent") else -1 if relation == "child" else 0)
    person = FamilyPerson.objects.create(room=room, gender=gender, generation=generation)
    people[key] = person
    if relation in ("father", "mother", "parent"):
        ParentChild.objects.create(parent=person, child=anchor)
    elif relation == "child":
        ParentChild.objects.create(parent=anchor, child=person)
        if co_parent:
            ParentChild.objects.create(parent=co_parent, child=person)
    else:
        Partnership.objects.create(first_id=min(person.pk, anchor.pk), second_id=max(person.pk, anchor.pk))
