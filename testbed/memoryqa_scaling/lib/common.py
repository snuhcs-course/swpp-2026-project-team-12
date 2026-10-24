"""Portable package paths and immutable experiment inputs. No services imported."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZES = (100, 200, 300)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def relative_path(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"Unsafe package path: {value}")
    result = (ROOT / path).resolve()
    if not result.is_relative_to(ROOT.resolve()):
        raise ValueError("Path escapes the package")
    return result


def manifest():
    data = read(ROOT / "image_manifest.json")
    rows = data["images"]
    if len(rows) != 120 or len({r["image_id"] for r in rows}) != 120:
        raise ValueError("Expected 120 distinct image IDs")
    if len({r["path"] for r in rows}) != 120:
        raise ValueError("Duplicate image destination")
    for row in rows:
        relative_path(row["path"])
        entry = row["archive_entry"]
        if (Path(row["path"]).name != row["image_id"] + ".jpg"
                or Path(entry["name"]).name != row["image_id"] + ".jpg"
                or row["size_bytes"] != entry["size"]
                or len(row["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in row["sha256"])):
            raise ValueError("Inconsistent image manifest")
    return data


def image_destination(row, directory=None):
    return Path(directory) / Path(row["path"]).name if directory else relative_path(row["path"])


def dataset(size):
    base = ROOT / f"datasets/history_{size}"
    memory = read(base / "memory_posts.json")
    probes = read(base / "probe_posts.json")
    family = read(base / "family.json")
    return {
        "memory": {p["post_key"]: p for p in memory},
        "probes": {p["post_key"]: p for p in probes},
        "family": family,
        "people": {m["key"]: m["name"] for m in family["members"]},
        "descriptions": {r["post_key"]: r for r in read(ROOT / f"snapshots/history_{size}/descriptions.json")["records"]},
        "db": read(ROOT / f"snapshots/history_{size}/db_import.json"),
    }


def resolved_task(task):
    return {**task, "image_path": str(relative_path(task["image_path"]))}
