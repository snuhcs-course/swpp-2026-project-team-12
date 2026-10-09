"""Generate ElevenLabs speech and cache it by family room and voice settings."""

import hashlib
import json
import os
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from django.conf import settings


class SpeechUnavailable(Exception):
    pass


_locks = [threading.Lock() for _ in range(32)]
MAX_AUDIO_BYTES = 16 * 1024 * 1024


def synthesize(text, room_id):
    if not settings.ELEVENLABS_VOICE_ID:
        raise SpeechUnavailable("A voice has not been configured.")
    key = hashlib.sha256(json.dumps([
        room_id, settings.ELEVENLABS_TTS_MODEL, settings.ELEVENLABS_VOICE_ID, text,
    ], ensure_ascii=False).encode()).hexdigest()
    folder = Path(settings.MEDIA_ROOT) / "speech"
    path = folder / (key + ".mp3")
    with _locks[int(key[:8], 16) % len(_locks)]:
        if path.exists():
            return path.read_bytes()
        if not settings.ELEVENLABS_API_KEY:
            raise SpeechUnavailable("Speech playback is not configured.")
        request = urllib.request.Request(
            "https://api.elevenlabs.io/v1/text-to-speech/"
            + urllib.parse.quote(settings.ELEVENLABS_VOICE_ID, safe="")
            + "?output_format=mp3_44100_128",
            data=json.dumps({
                "text": text,
                "model_id": settings.ELEVENLABS_TTS_MODEL,
                "voice_settings": {"speed": 0.85},
            }).encode(),
            headers={
                "xi-api-key": settings.ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                audio = response.read(MAX_AUDIO_BYTES + 1)
                content_type = response.headers.get("Content-Type", "").split(";")[0].lower().strip()
            if not audio or len(audio) > MAX_AUDIO_BYTES or content_type not in {"audio/mpeg", "audio/mp3"}:
                raise SpeechUnavailable("The provider did not return playable audio.")
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=folder, delete=False) as temporary:
                temp_path = Path(temporary.name)
                temporary.write(audio)
            try:
                os.replace(temp_path, path)
            finally:
                temp_path.unlink(missing_ok=True)
            return audio
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise SpeechUnavailable("Speech playback failed.") from error
