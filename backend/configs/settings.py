"""Django settings for the backend baseline and account authentication."""

import os
from pathlib import Path


# ============ BASE_DIR and path ============
BASE_DIR = Path(__file__).resolve().parent.parent  # BASE_DIR = backend/

# ============ Django Environment Settings ============
# Environment variables supplied by the process take precedence.
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-test-only")
if not DEBUG and SECRET_KEY == "local-test-only":
    # Defensive programming: prevent accidental deployment with a default secret key (security).
    raise RuntimeError("Set DJANGO_SECRET_KEY before running with DEBUG=0.")

# Allowed hosts settings
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]

# Apps and middleware settings
# Account APIs can run without AI credentials; providers will validate their keys when added.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "apps.accounts",
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

# ============ other settings ============
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_TZ = True

DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
