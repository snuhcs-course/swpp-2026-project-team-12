"""Look up the TTS voices accounts can choose; settings.TTS_VOICES is the one list to edit."""

from pathlib import Path

from django.conf import settings
from django.core import checks

# Every voice reads the same line so people can compare them. Samples are generated once with
# `manage.py generate_voice_samples` and committed; they are named by voice ID, so changing an
# entry's voice_id simply leaves its new sample to be generated.
SAMPLE_TEXT = "가족의 일상을 잇는 따뜻한 공간, 토닥"
SAMPLE_DIR = Path(__file__).resolve().parent / "samples"


def is_known(key):
    return isinstance(key, str) and key in settings.TTS_VOICES


def effective(key):
    """Accounts that never chose a voice, or whose voice was removed, use the default."""
    return key if is_known(key) else settings.TTS_DEFAULT_VOICE


def voice_id(key):
    return settings.TTS_VOICES.get(effective(key), {}).get("voice_id", "")


def sample_path(key):
    """The stored sample for a listed voice, or None when there is none to play."""
    voice = settings.TTS_VOICES.get(key) if isinstance(key, str) else None
    if not voice or not voice.get("voice_id"):
        return None
    path = SAMPLE_DIR / (voice["voice_id"] + ".mp3")
    return path if path.is_file() else None


def available():
    """Voices clients may offer; entries without a configured voice ID are hidden."""
    return [
        {"key": key, "name": voice["name"], "description": voice.get("description", ""),
         "sample": sample_path(key) is not None}
        for key, voice in settings.TTS_VOICES.items()
        if voice.get("voice_id")
    ]


@checks.register()
def check_voice_list(app_configs, **kwargs):
    if settings.TTS_DEFAULT_VOICE not in settings.TTS_VOICES:
        return [checks.Error(
            f"TTS_DEFAULT_VOICE {settings.TTS_DEFAULT_VOICE!r} is not a key of TTS_VOICES.",
            hint="Set TTS_DEFAULT_VOICE to one of: " + ", ".join(settings.TTS_VOICES) + ".",
            id="speech.E001",
        )]
    return []
