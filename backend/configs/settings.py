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
]
MIDDLEWARE = []
ROOT_URLCONF = "configs.urls"
WSGI_APPLICATION = "configs.wsgi.application"

# Database and Authentication settings
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}
AUTH_USER_MODEL = "accounts.User"  # Use custom user model defined in apps.accounts.models.User
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"  # AutoField type for primary keys in models

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

# ============ Third-party API settings ============
# Account and family APIs can run without AI credentials. Providers validate keys when called.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_TTS_MODEL = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
ELEVENLABS_STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2")

# ============ other settings ============
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_TZ = True

DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_DIMENSION = 1600
