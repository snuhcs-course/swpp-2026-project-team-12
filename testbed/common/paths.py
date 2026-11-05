"""Fixed repository locations, JSON files, and dataset config lookup."""
from __future__ import annotations

import json
from pathlib import Path

TESTBED_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TESTBED_ROOT.parent
BACKEND_ROOT = REPO_ROOT / "backend"
DATASETS_ROOT = TESTBED_ROOT / "datasets"
OUTPUT_ROOT = TESTBED_ROOT / "output"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def dataset_config(value):
    """Accept a dataset name under datasets/, a dataset folder, or a config file path."""
    named = DATASETS_ROOT / str(value) / "config.json"
    if named.is_file():
        return named.resolve()
    path = Path(value)
    if path.is_dir():
        path = path / "config.json"
    if not path.is_file():
        raise FileNotFoundError(f"데이터셋 config를 찾을 수 없습니다: {value}")
    return path.resolve()


def config_relative(config_path, value):
    """Paths inside a dataset config are relative to that config's folder."""
    path = Path(value)
    return path if path.is_absolute() else Path(config_path).resolve().parent / path
