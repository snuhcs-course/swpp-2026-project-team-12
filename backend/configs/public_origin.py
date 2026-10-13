"""Validate the configured external address without trusting request headers."""

import re
from urllib.parse import urlsplit


def normalize_public_origin(value):
    if not value:
        return ""
    parsed = urlsplit(value.strip())
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[a-zA-Z0-9]+(?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", hostname)
        or ".." in hostname
    ):
        raise ValueError("Use an HTTPS origin, for example https://example.trycloudflare.com (without /api/).")
    port = parsed.port
    return "https://" + hostname + (":" + str(port) if port is not None and port != 443 else "")
