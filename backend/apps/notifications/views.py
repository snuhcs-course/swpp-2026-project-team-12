import uuid

from django.db import transaction

from apps.api import APIError, api, body, required
from .models import PushDevice


@api("PUT", "DELETE")
def device(request):
    data = body(request)
    try:
        installation = uuid.UUID(required(data, "installation_id"))
    except ValueError as error:
        raise APIError("기기 정보를 다시 확인해 주세요.") from error
    if request.method == "DELETE":
        PushDevice.objects.filter(installation_id=installation, session=request.access_token).delete()
        return {"ok": True}
    token = required(data, "token", 4096)
    with transaction.atomic():
        # FCM can rotate tokens, and one installation can switch accounts.
        PushDevice.objects.filter(token=token).exclude(installation_id=installation).delete()
        current = PushDevice.objects.select_for_update().filter(installation_id=installation).first()
        binding = current.binding if current and current.session_id == request.access_token.pk else uuid.uuid4()
        current, _ = PushDevice.objects.update_or_create(installation_id=installation, defaults={
            "token": token, "session": request.access_token, "binding": binding,
        })
    return {"binding": str(current.binding)}
