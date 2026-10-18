from django.conf import settings
from django.db import models

from apps.families.models import FamilyRoom


class Post(models.Model):
    room = models.ForeignKey(FamilyRoom, on_delete=models.CASCADE, related_name="posts")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    image = models.ImageField(upload_to="posts/%Y/%m/", blank=True)
    caption = models.CharField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def photo_files(self):
        return [image for image in [self.image, *(photo.image for photo in self.photos.all())] if image]


class PostPhoto(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="posts/%Y/%m/")
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["position", "id"]
        constraints = [models.UniqueConstraint(fields=["post", "position"], name="unique_post_photo_position")]


class AdaptedMessage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="messages")
    viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField(blank=True)
    status = models.CharField(max_length=12, default="pending")
    prompt_version = models.CharField(max_length=64, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "viewer"], name="unique_adapted_message")]
