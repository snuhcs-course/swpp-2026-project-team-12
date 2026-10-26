"""Request options for one model group in settings."""

from django.conf import settings


def model_options(group):
    """A blank service tier or reasoning effort is not sent, so the API default applies."""
    options = {"model": getattr(settings, f"{group}_AI_MODEL")}
    if tier := getattr(settings, f"{group}_AI_SERVICE_TIER"):
        options["service_tier"] = tier
    if effort := getattr(settings, f"{group}_AI_REASONING_EFFORT"):
        options["reasoning"] = {"effort": effort}
    return options
