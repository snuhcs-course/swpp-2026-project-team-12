"""Wake the running supervisor only after a new family has been committed."""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from integrations.ai_workers.construction_manager import CONSTRUCTION_MANAGER

from .models import FamilyRoom


@receiver(post_save, sender=FamilyRoom, dispatch_uid="families.start_construction")
def family_created(sender, instance, created, raw, using, **kwargs):
    if created and not raw:
        transaction.on_commit(CONSTRUCTION_MANAGER.wake, using=using, robust=True)
