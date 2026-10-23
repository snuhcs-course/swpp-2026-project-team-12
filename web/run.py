"""Start both the desktop web client and the existing API in one process."""

import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="Run Talk Dock web and API together.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--skip-migrate", action="store_true")
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "configs.settings")
    try:
        import django
        from django.core.management import call_command
    except ImportError:
        parser.exit(1, "Install dependencies first: python -m pip install -r web/requirements.txt\n")
    django.setup()
    # Django's auto-reloader invokes this entry point again in its child process.
    if not args.skip_migrate and os.environ.get("RUN_MAIN") != "true":
        call_command("migrate", interactive=False)
    call_command("runserver", f"{args.host}:{args.port}", use_reloader=not args.no_reload)


if __name__ == "__main__":
    main()
