"""Minimal Django settings for the current test endpoint."""

import os


DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-test-only")
if not DEBUG and SECRET_KEY == "local-test-only":
    raise RuntimeError("Set DJANGO_SECRET_KEY before running with DEBUG=0.")

ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
INSTALLED_APPS = []
MIDDLEWARE = []
ROOT_URLCONF = "configs.urls"
WSGI_APPLICATION = "configs.wsgi.application"
