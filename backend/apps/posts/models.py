from django.conf import settings
from django.db import models

from apps.families.models import FamilyRoom


class Post(models.Model):
    room = models.ForeignKey(FamilyRoom, on_delete=models.CASCADE, related_name="posts")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    image = models.ImageField(upload_to="posts/%Y/%m/")
    caption = models.CharField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
