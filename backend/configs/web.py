"""Serve the small web client beside the existing authenticated API."""

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe


WEB_ROOT = Path(settings.BASE_DIR).parent / "web"
ASSETS = {
    "app.js": "text/javascript; charset=utf-8",
    "api.js": "text/javascript; charset=utf-8",
    "memory-search.js": "text/javascript; charset=utf-8",
    "daily-questions.js": "text/javascript; charset=utf-8",
    "daily-questions.css": "text/css; charset=utf-8",
    "family-tree.js": "text/javascript; charset=utf-8",
    "family-tree-view.js": "text/javascript; charset=utf-8",
    "floating-assistant.js": "text/javascript; charset=utf-8",
    "assistant-state.js": "text/javascript; charset=utf-8",
    "assistant_character.png": "image/png",
    "icons.js": "text/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
    "favicon.svg": "image/svg+xml",
    "todak_joy.gif": "image/gif",
}


def response_for(path, content_type):
    response = FileResponse(path.open("rb"), content_type=content_type)
    response["Cache-Control"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["X-Frame-Options"] = "DENY"
    response["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' blob: data:; media-src 'self' blob:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    return response


@require_safe
def index(request):
    return response_for(WEB_ROOT / "index.html", "text/html; charset=utf-8")


@require_safe
def asset(request, name):
    if name not in ASSETS:
        raise Http404
    return response_for(WEB_ROOT / "assets" / name, ASSETS[name])
