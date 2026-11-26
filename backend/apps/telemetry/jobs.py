from contextlib import contextmanager
from django.db.models import F
from django.utils import timezone
from integrations.telemetry import bind, context, emit, stage
from .models import WorkItem


def enqueue(kind, source_key, queued_at=None):
    current = context.get()
    defaults = {"queued_at": queued_at or timezone.now()}
    if current.get("operation_id"):
        defaults["operation_id"] = current["operation_id"]
    defaults["request_id"] = current.get("request_id", "")
    item, created = WorkItem.objects.get_or_create(kind=kind, source_key=str(source_key), defaults=defaults)
    if created:
        with bind(operation_id=str(item.operation_id), request_id=item.request_id,
                  job_id=str(item.pk), component=kind):
            emit("job_queued", result="success")
    return item


@contextmanager
def processing(item):
    now = timezone.now()
    WorkItem.objects.filter(pk=item.pk).update(started_at=now, status="running", attempts=F("attempts") + 1)
    item.refresh_from_db()
    with bind(operation_id=str(item.operation_id), request_id=item.request_id, job_id=str(item.pk),
              component=item.kind, attempt=item.attempts):
        emit("queue_wait", duration_ms=max(0, (now - item.queued_at).total_seconds() * 1000), result="success")
        try:
            with stage("job_execution"):
                yield
        except BaseException:
            WorkItem.objects.filter(pk=item.pk).update(status="error")
            raise
        else:
            WorkItem.objects.filter(pk=item.pk).update(status="success", completed_at=timezone.now())
