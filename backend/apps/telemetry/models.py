import uuid
from django.db import models


class WorkItem(models.Model):
    """Correlation and progress only. User content stays in the source models."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=24)
    source_key = models.CharField(max_length=80)
    operation_id = models.UUIDField(default=uuid.uuid4)
    request_id = models.CharField(max_length=36, blank=True)
    queued_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, default="pending", db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "source_key"], name="unique_telemetry_work")]
