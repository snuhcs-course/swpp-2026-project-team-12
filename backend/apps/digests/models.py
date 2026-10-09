from django.db import models

from apps.families.models import FamilyRoom
from apps.posts.models import Post


class Digest(models.Model):
    room = models.ForeignKey(FamilyRoom, on_delete=models.CASCADE, related_name="digests")
    date = models.DateField()
    text = models.TextField(blank=True)
    status = models.CharField(max_length=12, default="pending")
    window_start = models.DateTimeField(null=True)
    window_end = models.DateTimeField(null=True)
    posts = models.ManyToManyField(Post)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [models.UniqueConstraint(fields=["room", "date"], name="unique_daily_digest")]
