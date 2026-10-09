from django.http import HttpResponse

from apps.api import APIError, api, body
from apps.posts.services import current_room, post_for

from . import provider


@api("POST")
def transcribe(request, pk):
    post_for(request, pk)
    audio = request.FILES.get("audio")
    if not audio or audio.size > 5 * 1024 * 1024:
        raise APIError("짧게 녹음한 음성을 다시 올려 주세요. 음성은 5MB까지 사용할 수 있어요.")
    header = audio.read(16)
    audio.seek(0)
    if not (header[4:8] == b"ftyp" or header[:4] in {b"RIFF", b"OggS", b"\x1aE\xdf\xa3"}):
        raise APIError("읽을 수 없는 음성이에요. 다시 말해 주세요.")
    try:
        return {"recognized": provider.transcribe(audio)}
    except provider.NoSpeech as error:
        raise APIError("말씀을 듣지 못했거나 너무 길어요. 짧게 다시 말해 주세요.") from error
    except provider.SpeechUnavailable as error:
        raise APIError("말씀을 글로 바꾸지 못했어요. 잠시 후 다시 시도해 주세요.", 503) from error


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
