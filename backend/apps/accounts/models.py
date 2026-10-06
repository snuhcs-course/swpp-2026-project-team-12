import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Gender(models.TextChoices):
        UNKNOWN = "unknown", "Unspecified"
        MALE = "male", "Male"
        FEMALE = "female", "Female"

    display_name = models.CharField(max_length=40)
    gender = models.CharField(max_length=10, choices=Gender.choices, default=Gender.UNKNOWN)


class AccessToken(models.Model):
    # Authentication will store only a SHA-256 digest of the bearer token.
    digest = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="access_tokens")
    expires_at = models.DateTimeField()

    @classmethod
    def issue(cls, user):
        """Construct a new access token for the given user and return the raw token string."""
        raw = secrets.token_urlsafe(32)
        cls.objects.create(
            user=user,
            digest=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        return raw

    @classmethod
    def from_raw(cls, raw):
        """Return the AccessToken instance corresponding to the given raw token string, or None if not found."""
        if not raw:
            return None
        return cls.objects.select_related("user").filter(
            digest=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at__gt=timezone.now(),
            user__is_active=True,
        ).first()
