"""Django settings for account, family, and post APIs."""

import os
from pathlib import Path

from .public_origin import normalize_public_origin


# ============ BASE_DIR and path ============
BASE_DIR = Path(__file__).resolve().parent.parent  # BASE_DIR = backend/


def load_local_env(path):
    """Apply local .env values without overriding process environment variables."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_local_env(BASE_DIR.parent / ".env")

# ============ Django Environment Settings ============
# Environment variables supplied by the process take precedence.
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-test-only")
if not DEBUG and SECRET_KEY == "local-test-only":
    # Defensive programming: prevent accidental deployment with a default secret key (security).
    raise RuntimeError("Set DJANGO_SECRET_KEY before running with DEBUG=0.")

# Allowed hosts settings
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if host.strip()
]
try:
    PUBLIC_ORIGIN = normalize_public_origin(os.getenv("PUBLIC_ORIGIN", ""))
except ValueError as error:
    raise RuntimeError(str(error)) from error

# Apps and middleware settings
# Account APIs can run without AI credentials; providers will validate their keys when added.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "apps.accounts",
    "apps.families",
    "apps.posts",
    "apps.replies",
    "apps.digests",
    "apps.searching",
]
MIDDLEWARE = []
ROOT_URLCONF = "configs.urls"
WSGI_APPLICATION = "configs.wsgi.application"

# Database and Authentication settings
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.getenv("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 20},
    }
}
AUTH_USER_MODEL = "accounts.User"  # Use custom user model defined in apps.accounts.models.User
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
     "OPTIONS": {"user_attributes": ["username", "display_name"]}},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "apps.accounts.validators.NumberRequiredValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"  # AutoField type for primary keys in models

MEDIA_ROOT = Path(os.getenv("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "/media/"

# ============ Third-party API settings ============
# Account and family APIs can run without AI credentials. Providers validate keys when called.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# Model groups. An unset group value uses DEFAULT_AI_*; a blank tier or effort is not sent,
# so the API default applies.
DEFAULT_AI_MODEL = os.getenv("DEFAULT_AI_MODEL", "gpt-6-luna")
DEFAULT_AI_SERVICE_TIER = os.getenv("DEFAULT_AI_SERVICE_TIER", "fast")
DEFAULT_AI_REASONING_EFFORT = os.getenv("DEFAULT_AI_REASONING_EFFORT", "none")
# Summaries: daily digest, graph post descriptions and feed summaries.
SUMMARY_AI_MODEL = os.getenv("SUMMARY_AI_MODEL", DEFAULT_AI_MODEL)
SUMMARY_AI_SERVICE_TIER = os.getenv("SUMMARY_AI_SERVICE_TIER", DEFAULT_AI_SERVICE_TIER)
SUMMARY_AI_REASONING_EFFORT = os.getenv("SUMMARY_AI_REASONING_EFFORT", DEFAULT_AI_REASONING_EFFORT)
# Voice reply STT correction.
STT_AI_MODEL = os.getenv("STT_AI_MODEL", DEFAULT_AI_MODEL)
STT_AI_SERVICE_TIER = os.getenv("STT_AI_SERVICE_TIER", DEFAULT_AI_SERVICE_TIER)
STT_AI_REASONING_EFFORT = os.getenv("STT_AI_REASONING_EFFORT", DEFAULT_AI_REASONING_EFFORT)
# Answers: family history search and post QA, including the QA search decision.
ANSWER_AI_MODEL = os.getenv("ANSWER_AI_MODEL", DEFAULT_AI_MODEL)
ANSWER_AI_SERVICE_TIER = os.getenv("ANSWER_AI_SERVICE_TIER", DEFAULT_AI_SERVICE_TIER)
ANSWER_AI_REASONING_EFFORT = os.getenv("ANSWER_AI_REASONING_EFFORT", DEFAULT_AI_REASONING_EFFORT)
# Search decision and queries for STT correction.
QUERY_AI_MODEL = os.getenv("QUERY_AI_MODEL", DEFAULT_AI_MODEL)
QUERY_AI_SERVICE_TIER = os.getenv("QUERY_AI_SERVICE_TIER", DEFAULT_AI_SERVICE_TIER)
QUERY_AI_REASONING_EFFORT = os.getenv("QUERY_AI_REASONING_EFFORT", DEFAULT_AI_REASONING_EFFORT)
# Graphiti entity and relation extraction and reranking. Graphiti has no service tier, and a
# blank reasoning effort keeps Graphiti's own default rather than DEFAULT_AI_REASONING_EFFORT.
GRAPHITI_MODEL = os.getenv("GRAPHITI_MODEL", DEFAULT_AI_MODEL)
GRAPHITI_REASONING_EFFORT = os.getenv("GRAPHITI_REASONING_EFFORT", "")
GRAPHITI_SEARCH_WORKERS = int(os.getenv("GRAPHITI_SEARCH_WORKERS", "4"))
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
# Voices an account can choose for TTS; a new voice only needs an entry here. The key is
# stored on User.tts_voice, so keep keys stable. "name" and "description" are shown in the
# apps, and "voice_id" is the ElevenLabs voice ID (not a secret). Entries without a
# voice_id are not offered. TTS_DEFAULT_VOICE must be one of the keys; accounts that never
# chose a voice follow it, so changing it needs no migration.
TTS_DEFAULT_VOICE = "m1"
TTS_VOICES = {
    "m1": {"name": "Mr.k", "voice_id": "LKOcTG4J4tYTPR9DnLeM", "description": "차분한 남성 목소리"},
    "m2": {"name": "Jangho", "voice_id": "UmYoqGlufKxhJ6NCx5Mv", "description": "허스키한 남성 목소리"},
    "m3": {"name": "Jangho", "voice_id": "SWu2lWaUX4JBPKyh7h1p", "description": "친근한 남성 목소리"},
    "f1": {"name": "Jiyoung", "voice_id": "AW5wrnG1jVizOYY7R1Oo", "description": "자연스러운 여성 목소리"},
    "f2": {"name": "Jiyoung", "voice_id": "O2KReOFLpoR65nz6C9Se", "description": "밝고 젊은 여성 목소리"},
}
ELEVENLABS_TTS_MODEL = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
ELEVENLABS_STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "eleven_v4")

# ============ other settings ============
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_TZ = True

DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_POST_IMAGES = 5
MAX_POST_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_DIMENSION = 1600
