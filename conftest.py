"""Pytest bootstrap shared by the backend and web suites."""
import os

# pytest-django reads settings after loading conftest.  Remove paths that may
# point to a manually seeded testbed database or its media directory.
os.environ.pop("DJANGO_DB_PATH", None)
os.environ.pop("DJANGO_MEDIA_ROOT", None)
