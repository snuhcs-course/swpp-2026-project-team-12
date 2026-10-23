"""Prepare the exact historical backend, leaving the current shared app intact."""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from .common import ROOT, read, sha


def verify_environment():
    from importlib import metadata
    if sys.version_info[:2] != (3, 12):
        raise ValueError("Use Python 3.12 for the frozen experiment runtime")
    errors=[]
    versions={}
    for line in (ROOT/"requirements.txt").read_text().splitlines():
        line=line.strip()
        if not line or line.startswith("#"):continue
        name,expected=line.split("==",1)
        try:actual=metadata.version(name)
        except metadata.PackageNotFoundError:actual=None
        if actual!=expected:errors.append(name)
        versions[name]=actual
    if errors:raise ValueError("Install the pinned requirements; mismatched/missing packages: "+", ".join(errors))
    return {"python":"3.12","pinned_packages_verified":len(versions)}


def backend_path():
    return ROOT / ".runtime/backend"


def verify_app():
    contract = read(ROOT / "snapshots/app_contract.json")
    backend = backend_path()
    missing = []
    for name, expected in contract["backend_files"].items():
        p = backend / name
        if not p.is_file() or sha(p) != expected:
            missing.append(name)
    if missing:
        raise ValueError("Pinned backend missing or changed; run prepare-app: " + ", ".join(missing[:5]))
    return {"app_commit": contract["backend_base_commit"], "verified_files": len(contract["backend_files"])}


def prepare_app():
    config = read(ROOT / "config.json")
    repo = ROOT.parents[1]
    # The historical commit is an ancestor of iteration-2-demo. No checkout/fetch occurs.
    try:
        archive = subprocess.check_output(["git", "-C", str(repo), "archive", "--format=tar", config["app_commit"], "backend"], stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        raise RuntimeError("Pinned commit unavailable. Clone the repository with history or fetch the commit, then rerun prepare-app.") from None
    destination = ROOT / ".runtime"
    destination.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for item in tar.getmembers():
            rel = Path(item.name)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] != "backend":
                raise RuntimeError("Unsafe source archive")
            if item.isdir():
                (destination / rel).mkdir(parents=True, exist_ok=True)
            elif item.isfile():
                target = destination / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(item).read())
            else:
                raise RuntimeError("Links are not allowed in the runtime source")
    return verify_app()


def bootstrap(size, output, *, require_key=False):
    verify_environment()
    verify_app()
    config = read(ROOT / "config.json")
    backend = backend_path()
    if (backend.parent / ".env").exists():
        raise RuntimeError("Runtime .env files are forbidden; use exported variables")
    if os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") != "https://api.openai.com/v1":
        raise ValueError("This frozen experiment uses api.openai.com directly")
    output = Path(output).resolve()
    if output == ROOT or output in ROOT.parents or output == backend:
        raise ValueError("Use an isolated output directory")
    if output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / "output"):
        raise ValueError("Within the package, generated files must stay under output/")
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(DJANGO_SETTINGS_MODULE="configs.settings", DJANGO_DB_PATH=str(output / "test.sqlite3"),
        GRAPHITI_TELEMETRY_ENABLED="false", POST_AI_MODEL=config["model"], POST_AI_SERVICE_TIER=config["service_tier"],
        POST_AI_REASONING_EFFORT=config["reasoning_effort"], GRAPHITI_MODEL=config["model"], OPENAI_MODEL=config["model"],
        DJANGO_DEBUG="1", DJANGO_SECRET_KEY="isolated-memoryqa-reproduction-only", PUBLIC_ORIGIN="")
    if require_key and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Export OPENAI_API_KEY for paid generation")
    sys.path.insert(0, str(backend))
    import django
    django.setup()
    from django.conf import settings
    if Path(settings.BASE_DIR).resolve() != backend.resolve():
        raise RuntimeError("A different Django app is already loaded; use a fresh process")
    if Path(settings.DATABASES["default"]["NAME"]).resolve() != output / "test.sqlite3":
        raise RuntimeError("A different database is loaded; use a fresh process")
    settings.MEDIA_ROOT = ROOT
    return config
