from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        from integrations.speech import voices  # noqa: F401  Registers the voice list check.
