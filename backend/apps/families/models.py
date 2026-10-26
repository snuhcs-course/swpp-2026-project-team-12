from datetime import time

from django.conf import settings
from django.db import models


class FamilyRoom(models.Model):
    name = models.CharField(max_length=60)
    invite_code = models.CharField(max_length=8, unique=True)
    password_hash = models.CharField(max_length=128)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_rooms")
    digest_time = models.TimeField(default=time(21))
    created_at = models.DateTimeField(auto_now_add=True)
    tree_version = models.PositiveIntegerField(default=0)
    graph_synced_version = models.IntegerField(default=-1)


class FamilyPerson(models.Model):
    """A person can exist in the tree before they have an app account."""

    room = models.ForeignKey(FamilyRoom, on_delete=models.CASCADE, related_name="people")
    name = models.CharField(max_length=40, blank=True)
    gender = models.CharField(max_length=10, default="unknown")
    generation = models.IntegerField(default=0)
    graphiti_uuid = models.UUIDField(null=True, blank=True, unique=True, editable=False)


class ParentChild(models.Model):
    parent = models.ForeignKey(FamilyPerson, on_delete=models.CASCADE, related_name="child_links")
    child = models.ForeignKey(FamilyPerson, on_delete=models.CASCADE, related_name="parent_links")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parent", "child"], name="unique_parent_child"),
            models.CheckConstraint(condition=~models.Q(parent=models.F("child")), name="parent_not_self"),
        ]


class Partnership(models.Model):
    # Canonical order prevents storing both (a, b) and (b, a).
    first = models.ForeignKey(FamilyPerson, on_delete=models.CASCADE, related_name="first_partnerships")
    second = models.ForeignKey(FamilyPerson, on_delete=models.CASCADE, related_name="second_partnerships")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["first", "second"], name="unique_partnership"),
            models.CheckConstraint(condition=models.Q(first__lt=models.F("second")), name="ordered_partnership"),
        ]


class Membership(models.Model):
    room = models.ForeignKey(FamilyRoom, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    person = models.OneToOneField(FamilyPerson, on_delete=models.CASCADE,
                                  related_name="membership")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["room", "user"], name="unique_family_member"),
        ]
