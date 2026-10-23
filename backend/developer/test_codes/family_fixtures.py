"""Small tree fixtures shared by API tests."""

from apps.families.models import FamilyPerson, Membership, ParentChild


def add_member(room, user, generation=0):
    person = FamilyPerson.objects.create(room=room, name=user.display_name,
                                         gender=user.gender, generation=generation)
    return Membership.objects.create(room=room, user=user, person=person)


def link_parent(room, parent, child, generations=1):
    parent_person = room.members.get(user=parent).person
    child_person = room.members.get(user=child).person
    for _ in range(1, generations):
        intermediate = FamilyPerson.objects.create(room=room, generation=parent_person.generation - 1)
        ParentChild.objects.create(parent=parent_person, child=intermediate)
        parent_person = intermediate
    ParentChild.objects.get_or_create(parent=parent_person, child=child_person)


def sample_family(room, owner, *, son=None, grandma=None):
    from apps.accounts.models import User

    members = {"owner": owner, "son": son, "paternal_grandma": grandma}
    for key, name, gender, generation in (
        ("paternal_grandma", "경자", "female", 2), ("maternal_grandma", "선희", "female", 2),
        ("father", "병호", "male", 1), ("mother", "지현", "female", 1),
        ("son", "준호", "male", -1), ("daughter", "수아", "female", -1),
    ):
        user = members.get(key)
        if user is None:
            user = User.objects.create_user(username=key, display_name=name, gender=gender,
                                            password="Relative-Passphrase1!")
            add_member(room, user, generation)
        members[key] = user
    # Replace the initial fixture's unknown intermediate parent with named people.
    room.people.filter(membership__isnull=True).delete()
    for parent, child in (("paternal_grandma", "father"), ("maternal_grandma", "mother"),
                          ("father", "owner"), ("mother", "owner"), ("owner", "son"), ("owner", "daughter")):
        link_parent(room, members[parent], members[child])
    return members
