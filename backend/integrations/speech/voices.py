"""Look up the TTS voices accounts can choose; settings.TTS_VOICES is the one list to edit."""

from django.conf import settings
from django.core import checks


def is_known(key):
    return isinstance(key, str) and key in settings.TTS_VOICES


def effective(key):
    """Accounts that never chose a voice, or whose voice was removed, use the default."""
    return key if is_known(key) else settings.TTS_DEFAULT_VOICE


def voice_id(key):
    return settings.TTS_VOICES.get(effective(key), {}).get("voice_id", "")


def available():
    """Voices clients may offer; entries without a configured voice ID are hidden."""
    return [
        {"key": key, "name": voice["name"], "description": voice.get("description", "")}
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
