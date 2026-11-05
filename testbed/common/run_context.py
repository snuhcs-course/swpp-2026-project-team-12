"""Where one dataset run lives on disk, its phase state, and the adapter bound to its test DB."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .django_adapter import TalkDockDjangoAdapter, event_image_paths, missing_photos
from .paths import BACKEND_ROOT, OUTPUT_ROOT, dataset_config, read_json, write_json


def default_family_id(dataset_name):
    """A stable room ID per dataset, so datasets sharing one Neo4j never share a Graphiti group."""
    return 1000 + int(hashlib.sha256(dataset_name.encode()).hexdigest(), 16) % 9000


@dataclass(frozen=True)
class PipelineContext:
    config: Path
    output: Path
    manifest: Path
    database: Path
    state: Path
    backend: Path
    settings_module: str
    dataset_name: str
    family_id: int

    @classmethod
    def create(cls, config, output=None, database=None, backend=BACKEND_ROOT, settings_module="configs.settings"):
        config_path = dataset_config(config)
        config_data = read_json(config_path)
        output_path = Path(output or OUTPUT_ROOT / config_data["dataset_name"]).resolve()
        return cls(
            config=config_path,
            output=output_path,
            manifest=output_path / "manifest.json",
            database=Path(database or output_path / "test.sqlite3").resolve(),
            state=output_path / "pipeline_state.json",
            backend=Path(backend).resolve(),
            settings_module=settings_module,
            dataset_name=config_data["dataset_name"],
            family_id=config_data.get("family_id") or default_family_id(config_data["dataset_name"]),
        )

    @property
    def database_state(self):
        return self.output / "database_state.json"

    def adapter(self, adapter_class=TalkDockDjangoAdapter):
        return adapter_class(
            backend_path=self.backend,
            database=self.database,
            media_root=self.output / "media",
            settings_module=self.settings_module,
        )


def load_pipeline_state(context):
    if not context.state.exists():
        return {"schema_version": 1, "dataset_name": context.dataset_name, "completed": {}}
    state = read_json(context.state)
    if state.get("dataset_name") != context.dataset_name:
        raise ValueError("pipeline state의 dataset_name이 config와 다릅니다.")
    state.setdefault("completed", {})
    return state


def mark_completed(context, phase, details=None, reset=False):
    state = load_pipeline_state(context)
    if reset:
        state["completed"] = {}
    state["completed"][phase] = {"at": datetime.now(timezone.utc).isoformat(), **(details or {})}
    write_json(context.state, state)


def load_database_state(context):
    if not context.database_state.is_file():
        raise FileNotFoundError(f"database state가 없습니다. 먼저 seed phase를 실행하세요: {context.database_state}")
    return read_json(context.database_state)


def ensure_seedable_manifest(context):
    if not context.manifest.is_file():
        raise FileNotFoundError(f"manifest가 없습니다. 먼저 build phase를 실행하세요: {context.manifest}")
    manifest = read_json(context.manifest)
    missing = [
        event["feed_key"]
        for event in manifest.get("events", [])
        if missing_photos(event)
        or not all((context.output / path).is_file() for path in event_image_paths(event))
    ]
    if missing:
        raise RuntimeError(
            f"DB seed에 필요한 이미지가 {len(missing)}개 없습니다. "
            "--skip-images 없이 build phase를 실행하세요."
        )
    return manifest
