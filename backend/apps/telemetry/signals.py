from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.posts.models import Post
from .jobs import enqueue


@receiver(post_save, sender=Post, dispatch_uid="telemetry_construction_source")
def post_created(sender, instance, created, raw=False, **kwargs):
    if created and not raw and instance.kind == "news":
        enqueue("construction", f"post:{instance.pk}", instance.created_at)
