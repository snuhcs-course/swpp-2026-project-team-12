"""Request options for one model group in settings."""

from django.conf import settings


def group_setting(group, name):
    """An unset group value falls back to DEFAULT_AI_<name>; a blank one stays blank."""
    value = getattr(settings, f"{group}_AI_{name}")
    return getattr(settings, f"DEFAULT_AI_{name}") if value is None else value


def model_options(group):
    """A blank service tier or reasoning effort is not sent, so the API default applies."""
    options = {"model": group_setting(group, "MODEL")}
    if tier := group_setting(group, "SERVICE_TIER"):
        options["service_tier"] = tier
    if effort := group_setting(group, "REASONING_EFFORT"):
        options["reasoning"] = {"effort": effort}
    return options
