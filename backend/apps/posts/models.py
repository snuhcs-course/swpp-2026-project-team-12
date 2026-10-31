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
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    kind = models.CharField(max_length=12, default="news", db_default="news", db_index=True)
    images = models.JSONField(default=list, blank=True)
    caption = models.CharField(max_length=2000, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.CheckConstraint(
            condition=models.Q(kind="question") | models.Q(author__isnull=False),
            name="news_requires_author",
        )]

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


class QuestionTemplate(models.Model):
    """An optional editorial override; otherwise the curated daily rotation is used."""

    date = models.DateField(unique=True)
    title = models.CharField(max_length=2000)
    kind = models.CharField(max_length=12)
    options = models.JSONField(default=list, blank=True)


class DailyQuestion(models.Model):
    post = models.OneToOneField(Post, on_delete=models.CASCADE, related_name="daily_question")
    room = models.ForeignKey(FamilyRoom, on_delete=models.CASCADE, related_name="daily_questions")
    date = models.DateField()
    kind = models.CharField(max_length=12, choices=[
        ("choice", "밸런스 게임"), ("text", "한 줄 답변"),
        ("weather", "오늘의 마음 날씨"), ("tier", "티어 리스트"),
    ])
    options = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [models.UniqueConstraint(fields=["room", "date"], name="one_question_per_room_day")]


class QuestionAnswer(models.Model):
    question = models.ForeignKey(DailyQuestion, on_delete=models.CASCADE, related_name="answers")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    choice = models.CharField(max_length=100, blank=True)
    other_text = models.CharField(max_length=100, blank=True, default="", db_default="")
    text = models.CharField(max_length=1000, blank=True)
    tiers = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=10, default="text")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["question", "author"], name="one_answer_per_person")]
