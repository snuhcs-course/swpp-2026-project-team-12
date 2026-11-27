from django.apps import AppConfig


class TelemetryConfig(AppConfig):
    name = "apps.telemetry"

    def ready(self):
        from . import signals  # noqa: F401
