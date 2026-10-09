from django.http import HttpResponse

from apps.api import APIError, api, body
from apps.posts.services import current_room

from . import provider


@api("POST")
def speak(request):
    room = current_room(request)
    raw = body(request).get("text", "")
    if not isinstance(raw, str):
        raise APIError("입력한 내용을 다시 확인해 주세요.")
    text = raw.strip()
    if not text or len(text) > 4000:
        raise APIError("입력한 내용을 다시 확인해 주세요.")
    try:
        audio = provider.synthesize(text, room.pk)
    except provider.SpeechUnavailable as error:
        raise APIError("소리를 준비하지 못했어요. 잠시 후 다시 시도해 주세요.", 503) from error
    return HttpResponse(audio, content_type="audio/mpeg")
