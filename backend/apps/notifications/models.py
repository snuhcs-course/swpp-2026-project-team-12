import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class PushDevice(models.Model):
    installation_id = models.UUIDField(unique=True)
    token = models.CharField(max_length=4096, unique=True)
    session = models.ForeignKey("accounts.AccessToken", on_delete=models.CASCADE)
    binding = models.UUIDField(default=uuid.uuid4)
    updated_at = models.DateTimeField(auto_now=True)


class PushNotification(models.Model):
    """Durable outbox; one independent retry/claim per receiving installation."""

    device = models.ForeignKey(PushDevice, on_delete=models.CASCADE)
    binding = models.UUIDField()
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    room = models.ForeignKey("families.FamilyRoom", on_delete=models.CASCADE)
    post = models.ForeignKey("posts.Post", on_delete=models.CASCADE)
    question = models.ForeignKey("posts.DailyQuestion", null=True, on_delete=models.CASCADE)
    event_key = models.CharField(max_length=100)
    kind = models.CharField(max_length=30)
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=400)
    created_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField()
    claimed_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, default="pending", db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["device", "event_key"], name="unique_device_push_event")]
