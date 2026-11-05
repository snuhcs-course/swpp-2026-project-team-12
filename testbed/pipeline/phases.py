"""Prepare a dataset's isolated test DB and Graphiti memory: build → seed-memory → construct → seed-probes.

Evaluation runs separately in testbed.feature_eval once the phases a feature needs are complete.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from ..builder.dataset_builder import generate
from ..common.django_adapter import TalkDockDjangoAdapter
from ..common.paths import BACKEND_ROOT, read_json, write_json
from ..common.run_context import (
    PipelineContext,
    ensure_seedable_manifest,
    load_database_state,
    load_pipeline_state,
    mark_completed,
)

PHASES = ("build", "seed-memory", "construct", "seed-probes")
DEPENDENCIES = {
    "seed-memory": "build",
    "construct": "seed-memory",
    "seed-probes": "construct",
}


def require_dependency(context, phase, force=False):
    dependency = DEPENDENCIES.get(phase)
    if not dependency or force:
        return
    if dependency not in load_pipeline_state(context)["completed"]:
        raise RuntimeError(
            f"{phase} 전에 {dependency} phase가 필요합니다. "
            "앞 단계부터 실행하거나 --force를 사용하세요."
        )


def step_done(message):
    print(f"  [step] {message} 완료", flush=True)


def events_for_seed_phase(manifest, phase):
    wanted_probe = phase == "probes"
    return [event for event in manifest["events"] if (event["kind"] == "probe") == wanted_probe]


def seed_events(context, events, default_password=None, adapter_class=TalkDockDjangoAdapter):
    manifest = read_json(context.manifest)
    adapter = context.adapter(adapter_class)
    try:
        adapter.setup()
        result = adapter.seed(manifest, context.manifest, events,
                              default_password=default_password, family_id=context.family_id)
    finally:
        adapter.close()

    database_state = read_json(context.database_state) if context.database_state.exists() else {}
    database_state.update({"database": str(context.database), "family_id": result["family_id"]})
    database_state.setdefault("post_ids", {}).update(result["post_ids"])
    write_json(context.database_state, database_state)
    return result


def phase_build(context, *, skip_images=False, **_):
    output, plan = generate(context.config, context.output, skip_images=skip_images)
    step_done("manifest와 이미지 생성")
    mark_completed(context, "build", {"event_count": len(plan["events"]), "images": not skip_images}, reset=True)
    return {"output": str(output), "event_count": len(plan["events"])}


def phase_seed_memory(context, *, force=False, default_password=None, **_):
    require_dependency(context, "seed-memory", force)
    manifest = ensure_seedable_manifest(context)
    result = seed_events(context, events_for_seed_phase(manifest, "memory"), default_password=default_password)
    step_done(f"기억용 게시물 {len(result['post_ids'])}개 seed")
    mark_completed(context, "seed-memory", {"post_count": len(result["post_ids"]), "family_id": result["family_id"]})
    return result


def phase_construct(context, *, force=False, **_):
    require_dependency(context, "construct", force)
    if not context.database.is_file():
        raise FileNotFoundError(f"test DB가 없습니다: {context.database}")
    family_id = load_database_state(context)["family_id"]
    manage = context.backend / "manage.py"
    if not manage.is_file():
        raise FileNotFoundError(f"TalkDock manage.py가 없습니다: {manage}")
    environment = os.environ.copy()
    environment["DJANGO_DB_PATH"] = str(context.database)
    environment["DJANGO_MEDIA_ROOT"] = str(context.output / "media")
    subprocess.run(
        [sys.executable, str(manage), "run_construction_worker", "--family-id", str(family_id), "--once"],
        cwd=context.backend,
        env=environment,
        check=True,
    )
    step_done("Graphiti 기억 구성")
    mark_completed(context, "construct", {"family_id": family_id})
    return {"family_id": family_id}


def phase_seed_probes(context, *, force=False, default_password=None, **_):
    require_dependency(context, "seed-probes", force)
    manifest = ensure_seedable_manifest(context)
    result = seed_events(context, events_for_seed_phase(manifest, "probes"), default_password=default_password)
    step_done(f"probe 게시물 {len(result['post_ids'])}개 seed")
    mark_completed(context, "seed-probes", {"post_count": len(result["post_ids"]), "family_id": result["family_id"]})
    return result


PHASE_HANDLERS = {
    "build": phase_build,
    "seed-memory": phase_seed_memory,
    "construct": phase_construct,
    "seed-probes": phase_seed_probes,
}


def normalize_phases(requested):
    if "all" in requested:
        if len(requested) != 1:
            raise ValueError("all은 다른 phase와 함께 지정할 수 없습니다.")
        return list(PHASES)
    indexes = [PHASES.index(phase) for phase in requested]
    if indexes != sorted(indexes):
        raise ValueError("phase는 build → seed-memory → construct → seed-probes 순서로 지정하세요.")
    return list(dict.fromkeys(requested))


def run_pipeline(context, phases, **options):
    results = {}
    for phase in normalize_phases(phases):
        print(f"[{phase}] 시작", flush=True)
        results[phase] = PHASE_HANDLERS[phase](context, **options)
        print(f"[{phase}] 완료", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="데이터셋의 test DB와 Graphiti 기억을 준비합니다.")
    parser.add_argument("--dataset", default="example", help="datasets/ 아래 폴더 이름 또는 config 경로")
    parser.add_argument("--output")
    parser.add_argument("--database")
    parser.add_argument("--backend", default=str(BACKEND_ROOT))
    parser.add_argument("--settings", default="configs.settings")
    parser.add_argument("--phase", action="append", required=True, choices=(*PHASES, "all"))
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--default-password")
    parser.add_argument("--force", action="store_true", help="이전 phase 완료 확인을 건너뜁니다.")
    args = parser.parse_args()

    context = PipelineContext.create(args.dataset, output=args.output, database=args.database,
                                     backend=args.backend, settings_module=args.settings)
    try:
        run_pipeline(context, args.phase, skip_images=args.skip_images,
                     default_password=args.default_password, force=args.force)
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
