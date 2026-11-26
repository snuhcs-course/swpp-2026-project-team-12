from django.apps import AppConfig


class FamiliesConfig(AppConfig):
    name = "apps.families"

    def ready(self):
        from . import signals  # noqa: F401  Register notifications without starting workers.
