from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.posts.models import DailyQuestion, Post, QuestionAnswer
from apps.replies.models import Comment
from .services import enqueue


@receiver(post_save, sender=Post)
def new_post(sender, instance, created, raw=False, **kwargs):
    if created and not raw and instance.kind == "news":
        enqueue(room=instance.room, post=instance, actor=instance.author,
                key=f"post:{instance.pk}", kind="post")


@receiver(post_save, sender=Comment)
def new_comment(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    post = instance.post
    question = DailyQuestion.objects.filter(post=post).select_related("post").first()
    if question:
        enqueue(room=post.room, post=post, actor=instance.author, key=f"comment:{instance.pk}",
                kind="question_comment", question=question, text=instance.text)
    elif post.author_id:
        enqueue(room=post.room, post=post, actor=instance.author, key=f"comment:{instance.pk}",
                kind="comment", text=instance.text, recipient_id=post.author_id)


@receiver(post_save, sender=QuestionAnswer)
def new_answer(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        question = instance.question
        enqueue(room=question.room, post=question.post, actor=instance.author,
                key=f"answer:{instance.pk}", kind="answer", question=question)
