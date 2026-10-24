from dataclasses import dataclass

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models

from apps.families.models import FamilyRoom


@dataclass(frozen=True)
class StoredPhoto:
    """A lazy storage reference; callers own and close the opened file."""

    name: str

    def open(self, mode="rb"):
        return default_storage.open(self.name, mode)


class Post(models.Model):
    room = models.ForeignKey(FamilyRoom, on_delete=models.CASCADE, related_name="posts")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    images = models.JSONField(default=list, blank=True)
    caption = models.CharField(max_length=2000, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def photo_files(self):
        return [StoredPhoto(name) for name in self.images]


class AdaptedMessage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="messages")
    viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField(blank=True)
    status = models.CharField(max_length=12, default="pending")
    prompt_version = models.CharField(max_length=64, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "viewer"], name="unique_adapted_message")]
