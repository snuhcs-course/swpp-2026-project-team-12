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


class Membership(models.Model):
    class Slot(models.TextChoices):
        OWNER = "owner", "Owner"
        FATHER = "father", "Father"
        MOTHER = "mother", "Mother"
        GRANDMA_FATHER = "grandma-father", "Paternal grandmother"
        GRANDMA_MOTHER = "grandma-mother", "Maternal grandmother"
        SON = "son", "Son"
        DAUGHTER = "daughter", "Daughter"
        GRANDSON = "grandson", "Grandson"
        GRANDDAUGHTER = "granddaughter", "Granddaughter"

    room = models.ForeignKey(FamilyRoom, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    slot = models.CharField(max_length=30, choices=Slot.choices)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["room", "user"], name="unique_family_member"),
            models.UniqueConstraint(fields=["room", "slot"], name="unique_family_slot"),
        ]
