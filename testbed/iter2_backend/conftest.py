"""Pytest bootstrap for the isolated Iteration 3 backend suite."""
import os

# pytest-django reads settings after loading conftest.  Remove paths that may
# point to a manually seeded testbed database or its media directory.
os.environ.pop("DJANGO_DB_PATH", None)
os.environ.pop("DJANGO_MEDIA_ROOT", None)
