from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from adapters.talkdock_django import TalkDockDjangoAdapter
from dataset_builder import generate, read_json


ROOT = Path(__file__).resolve().parent
DEFAULT_BACKEND = ROOT.parents[1] / "backend"
PHASES = ("build", "seed-memory", "construct", "seed-probes", "evaluate")
DEPENDENCIES = {
    "seed-memory": "build",
    "construct": "seed-memory",
    "seed-probes": "construct",
    "evaluate": "seed-probes",
}


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

    @classmethod
    def create(cls, config, output=None, database=None, backend=DEFAULT_BACKEND, settings_module="configs.settings"):
        config_path = Path(config).resolve()
        config_data = read_json(config_path)
        output_path = Path(output or ROOT / "output" / config_data["dataset_name"]).resolve()
        return cls(
            config=config_path,
            output=output_path,
            manifest=output_path / "manifest.json",
            database=Path(database or output_path / "test.sqlite3").resolve(),
            state=output_path / "pipeline_state.json",
            backend=Path(backend).resolve(),
            settings_module=settings_module,
            dataset_name=config_data["dataset_name"],
        )


def load_pipeline_state(context):
    if not context.state.exists():
        return {"schema_version": 1, "dataset_name": context.dataset_name, "completed": {}}
    state = read_json(context.state)
    if state.get("dataset_name") != context.dataset_name:
        raise ValueError("pipeline state??dataset_name??config? ?ㅻ쫭?덈떎.")
    state.setdefault("completed", {})
    return state


def save_pipeline_state(context, state):
    context.output.mkdir(parents=True, exist_ok=True)
    context.state.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_completed(context, phase, details=None, reset=False):
    state = load_pipeline_state(context)
    if reset:
        state["completed"] = {}
    state["completed"][phase] = {
        "at": datetime.now(timezone.utc).isoformat(),
        **(details or {}),
    }
    save_pipeline_state(context, state)


def require_dependency(context, phase, force=False):
    dependency = DEPENDENCIES.get(phase)
    if not dependency or force:
        return
    completed = load_pipeline_state(context)["completed"]
    if dependency not in completed:
        raise RuntimeError(
            f"{phase} ?꾩뿉 {dependency} phase媛 ?꾩슂?⑸땲?? "
            "???④퀎遺???ㅽ뻾?섍굅??--force瑜??ъ슜?섏꽭??"
        )


def ensure_seedable_manifest(context):
    if not context.manifest.is_file():
        raise FileNotFoundError(f"manifest媛 ?놁뒿?덈떎: {context.manifest}")
    manifest = read_json(context.manifest)
    missing = [
        event["feed_key"]
        for event in manifest.get("events", [])
        if not event.get("image_path") or not (context.output / event["image_path"]).is_file()
    ]
    if missing:
        raise RuntimeError(
            f"DB seed???꾩슂???대?吏媛 {len(missing)}媛??놁뒿?덈떎. "
            "--skip-images ?놁씠 build phase瑜??ㅽ뻾?섏꽭??"
        )
    return manifest


def expected_evaluation_cases(manifest):
    members = manifest["family"]["members"]
    relationships = manifest["family"]["relationship_matrix"]
    expected = []
    for event in manifest["events"]:
        if event["kind"] != "probe":
            continue
        for viewer in members:
            expected.append({
                "case_id": f"{event['feed_key']}__{viewer['username']}",
                "probe_feed_key": event["feed_key"],
                "thread_id": event["thread_id"],
                "viewer_username": viewer["username"],
                "expected_relationship": relationships[viewer["username"]][event["author_username"]],
                "question": event["evaluation_question"],
                "required_memories": event["required_memories"],
                "optional_memories": event.get("optional_memories", []),
                "must_filter": event["must_filter"],
            })
    return expected


def load_frozen_evaluation_set(context, manifest):
    config = read_json(context.config)
    configured_path = config.get("evaluation_set")
    if not configured_path:
        return None
    evaluation_path = Path(configured_path)
    if not evaluation_path.is_absolute():
        evaluation_path = ROOT / evaluation_path
    suite = read_json(evaluation_path)
    if suite.get("status") != "frozen":
        raise ValueError(f"evaluation_set must be frozen: {evaluation_path}")
    expected = expected_evaluation_cases(manifest)
    actual = suite.get("cases")
    if actual != expected:
        raise ValueError(
            "Frozen evaluation set does not match the generated probe/viewer cases. "
            "Create a new versioned evaluation set; do not edit the frozen set."
        )
    return {
        "suite_id": suite.get("suite_id"),
        "case_count": suite.get("case_count"),
        "path": str(evaluation_path),
        "plan_sha256": suite.get("plan_sha256"),
    }


def evaluate_thresholds(metrics, threshold_spec):
    results = {}
    for metric, rule in threshold_spec["metrics"].items():
        actual = metrics.get(metric)
        operator = rule["operator"]
        target = rule["target"]
        if actual is None:
            passed = False
        elif operator == ">=":
            passed = actual >= target
        elif operator == "<=":
            passed = actual <= target
        else:
            raise ValueError(f"Unsupported threshold operator: {operator}")
        results[metric] = {
            "actual": actual,
            "operator": operator,
            "target": target,
            "passed": passed,
            "rationale": rule.get("rationale", ""),
        }
    return results


def load_threshold_spec(context):
    config = read_json(context.config)
    configured_path = config.get("evaluation_thresholds")
    if not configured_path:
        return None, None
    threshold_path = Path(configured_path)
    if not threshold_path.is_absolute():
        threshold_path = ROOT / threshold_path
    return read_json(threshold_path), threshold_path


def step_done(message):
    print(f"  [step] {message} ?앸궗?듬땲??", flush=True)


def events_for_seed_phase(manifest, phase):
    wanted_probe = phase == "probes"
    return [
        event for event in manifest["events"]
        if (event["kind"] == "probe") == wanted_probe
    ]


def seed_events(context, events, default_password=None, adapter_class=TalkDockDjangoAdapter):
    manifest = read_json(context.manifest)
    adapter = adapter_class(
        backend_path=context.backend,
        database=context.database,
        media_root=context.output / "media",
        settings_module=context.settings_module,
    )
    try:
        adapter.setup()
        result = adapter.seed(
            manifest,
            context.manifest,
            events,
            default_password=default_password,
        )
    finally:
        adapter.close()

    database_state_path = context.output / "database_state.json"
    database_state = read_json(database_state_path) if database_state_path.exists() else {}
    database_state.update({"database": str(context.database), "family_id": result["family_id"]})
    database_state.setdefault("post_ids", {}).update(result["post_ids"])
    database_state_path.write_text(
        json.dumps(database_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def phase_build(context, *, skip_images=False, **_):
    output, plan = generate(context.config, context.output, skip_images=skip_images)
    step_done("manifest? ?대?吏 ?앹꽦")
    mark_completed(
        context,
        "build",
        {"event_count": len(plan["events"]), "images": not skip_images},
        reset=True,
    )
    step_done("build ?곹깭 湲곕줉")
    return {"output": str(output), "event_count": len(plan["events"])}


def phase_seed_memory(context, *, force=False, default_password=None, **_):
    require_dependency(context, "seed-memory", force)
    manifest = ensure_seedable_manifest(context)
    step_done("memory seed input verified")
    result = seed_events(
        context,
        events_for_seed_phase(manifest, "memory"),
        default_password=default_password,
    )
    step_done(f"seeded {len(result['post_ids'])} memory posts")
    mark_completed(context, "seed-memory", {"post_count": len(result["post_ids"]), "family_id": result["family_id"]})
    step_done("seed-memory ?곹깭 湲곕줉")
    return result


def phase_construct(context, *, force=False, **_):
    require_dependency(context, "construct", force)
    if not context.database.is_file():
        raise FileNotFoundError(f"?뚯뒪??DB媛 ?놁뒿?덈떎: {context.database}")
    database_state = context.output / "database_state.json"
    if not database_state.is_file():
        raise FileNotFoundError(f"database state媛 ?놁뒿?덈떎: {database_state}")
    family_id = read_json(database_state)["family_id"]
    manage = context.backend / "manage.py"
    if not manage.is_file():
        raise FileNotFoundError(f"TalkDock manage.py媛 ?놁뒿?덈떎: {manage}")
    environment = os.environ.copy()
    environment["DJANGO_DB_PATH"] = str(context.database)
    environment["DJANGO_MEDIA_ROOT"] = str(context.output / "media")
    subprocess.run(
        [sys.executable, str(manage), "run_construction_worker", "--family-id", str(family_id), "--once"],
        cwd=context.backend,
        env=environment,
        check=True,
    )
    step_done("Graphiti memory construction")
    mark_completed(context, "construct", {"family_id": family_id})
    step_done("construct ?곹깭 湲곕줉")
    return {"family_id": family_id}


def phase_seed_probes(context, *, force=False, default_password=None, **_):
    require_dependency(context, "seed-probes", force)
    manifest = ensure_seedable_manifest(context)
    step_done("probe seed input verified")
    result = seed_events(
        context,
        events_for_seed_phase(manifest, "probes"),
        default_password=default_password,
    )
    step_done(f"seeded {len(result['post_ids'])} probe posts")
    mark_completed(context, "seed-probes", {"post_count": len(result["post_ids"]), "family_id": result["family_id"]})
    step_done("seed-probes ?곹깭 湲곕줉")
    return result


def retrieved_feed_keys(memories, post_ids):
    by_source_name = {f"post_{post_id}": feed_key for feed_key, post_id in post_ids.items()}
    keys = []
    for memory in memories:
        for source in memory.get("sources", []):
            feed_key = by_source_name.get(source.get("name"))
            if feed_key and feed_key not in keys:
                keys.append(feed_key)
    return keys


def evaluate_cases(manifest, database_state, cases):
    events = {event["feed_key"]: event for event in manifest["events"]}
    establishes = {
        feed_key: set(event.get("establishes", []))
        for feed_key, event in events.items()
    }
    evaluated = []
    for case in cases:
        probe = events[case["feed_key"]]
        retrieved = retrieved_feed_keys(case["memories"], database_state["post_ids"])
        retrieved_labels = set().union(*(establishes.get(key, set()) for key in retrieved)) if retrieved else set()
        required = set(probe.get("required_memories", []))
        optional = set(probe.get("optional_memories", []))
        forbidden = set(probe.get("must_filter", []))
        relevant_sources = [key for key in retrieved if establishes.get(key, set()) & (required | optional)]
        evaluated.append({
            **case,
            "retrieved_feed_keys": retrieved,
            "retrieved_labels": sorted(retrieved_labels),
            "required_found": sorted(required & retrieved_labels),
            "required_missing": sorted(required - retrieved_labels),
            "forbidden_retrieved": sorted(forbidden & retrieved_labels),
            "required_recall": len(required & retrieved_labels) / len(required) if required else 1.0,
            "retrieval_source_precision": len(relevant_sources) / len(retrieved) if retrieved else 0.0,
            "relationship_mentioned": case["expected_relationship"] in case["answer"],
            "schema_valid": bool(case["answer"].strip()) and isinstance(case.get("queries", []), list)
            and isinstance(case.get("memories", []), list),
        })

    count = len(evaluated)
    probes = {}
    for row in evaluated:
        probes.setdefault(row["feed_key"], []).append(row)
    probe_diversity = {
        feed_key: len({row["answer"].strip() for row in rows}) / len(rows)
        for feed_key, rows in probes.items()
    }
    metrics = {
        "case_count": count,
        "mean_required_recall": sum(row["required_recall"] for row in evaluated) / count if count else 0.0,
        "mean_retrieval_source_precision": sum(row["retrieval_source_precision"] for row in evaluated) / count if count else 0.0,
        "filter_leakage_case_rate": sum(bool(row["forbidden_retrieved"]) for row in evaluated) / count if count else 0.0,
        "relationship_mention_rate": sum(row["relationship_mentioned"] for row in evaluated) / count if count else 0.0,
        "search_rate": sum(bool(row["query"]) for row in evaluated) / count if count else 0.0,
        "mean_answer_diversity": sum(probe_diversity.values()) / len(probe_diversity) if probe_diversity else 0.0,
        "answer_diversity_by_probe": probe_diversity,
        "schema_validity_rate": sum(row["schema_valid"] for row in evaluated) / count if count else 0.0,
        "case_retrieval_pass_rate": sum(
            row["required_recall"] == 1.0 and not row["forbidden_retrieved"] for row in evaluated
        ) / count if count else 0.0,
    }
    return evaluated, metrics


def phase_evaluate(context, *, force=False, **_):
    require_dependency(context, "evaluate", force)
    manifest = ensure_seedable_manifest(context)
    frozen_evaluation_set = load_frozen_evaluation_set(context, manifest)
    database_state_path = context.output / "database_state.json"
    if not database_state_path.is_file():
        raise FileNotFoundError(f"database state媛 ?놁뒿?덈떎: {database_state_path}")
    database_state = read_json(database_state_path)
    step_done("evaluation input verified")

    adapter = TalkDockDjangoAdapter(
        backend_path=context.backend,
        database=context.database,
        media_root=context.output / "media",
        settings_module=context.settings_module,
    )

    def report_case(probe_index, probe_count, viewer_index, viewer_count, feed_key, viewer_name):
        step_done(
            f"?됯? {probe_index}/{probe_count}, 媛議?{viewer_index}/{viewer_count} "
            f"({feed_key}, {viewer_name})"
        )

    try:
        adapter.setup()
        cases = adapter.evaluate(manifest, database_state, on_case_done=report_case)
    finally:
        adapter.close()
    step_done(f"collected {len(cases)} QA results")

    evaluated, metrics = evaluate_cases(manifest, database_state, cases)
    threshold_spec, threshold_path = load_threshold_spec(context)
    threshold_results = evaluate_thresholds(metrics, threshold_spec) if threshold_spec else None
    report = {
        "schema_version": 2,
        "dataset_name": context.dataset_name,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "frozen_evaluation_set": frozen_evaluation_set,
        "metrics": metrics,
        "thresholds": {
            "path": str(threshold_path),
            "version": threshold_spec.get("version"),
            "results": threshold_results,
        } if threshold_spec else None,
        "cases": evaluated,
    }
    report_path = context.output / "evaluation.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    step_done(f"wrote evaluation report: {report_path.name}")
    mark_completed(context, "evaluate", {"case_count": len(cases), "report": str(report_path)})
    step_done("evaluate ?곹깭 湲곕줉")
    return {"report": str(report_path), "metrics": metrics}


PHASE_HANDLERS = {
    "build": phase_build,
    "seed-memory": phase_seed_memory,
    "construct": phase_construct,
    "seed-probes": phase_seed_probes,
    "evaluate": phase_evaluate,
}


def normalize_phases(requested):
    if "all" in requested:
        if len(requested) != 1:
            raise ValueError("all? ?ㅻⅨ phase? ?④퍡 吏?뺥븷 ???놁뒿?덈떎.")
        return list(PHASES)
    indexes = [PHASES.index(phase) for phase in requested]
    if indexes != sorted(indexes):
        raise ValueError("phase??build ??seed-memory ??construct ??seed-probes ??evaluate ?쒖꽌濡?吏?뺥븯?몄슂.")
    return list(dict.fromkeys(requested))


def run_pipeline(context, phases, **options):
    results = {}
    for phase in normalize_phases(phases):
        print(f"[{phase}] ?쒖옉?⑸땲??", flush=True)
        results[phase] = PHASE_HANDLERS[phase](context, **options)
        print(f"[{phase}] ?앸궗?듬땲??", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="媛議?memory testbed phase pipeline")
    parser.add_argument("--config", default=str(ROOT / "input" / "config.example.json"))
    parser.add_argument("--output")
    parser.add_argument("--database")
    parser.add_argument("--backend", default=str(DEFAULT_BACKEND))
    parser.add_argument("--settings", default="configs.settings")
    parser.add_argument("--phase", action="append", required=True, choices=(*PHASES, "all"))
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--default-password")
    parser.add_argument("--force", action="store_true", help="?댁쟾 phase ?꾨즺 ?뺤씤??嫄대꼫?곷땲??")
    args = parser.parse_args()

    context = PipelineContext.create(
        args.config,
        output=args.output,
        database=args.database,
        backend=args.backend,
        settings_module=args.settings,
    )
    try:
        run_pipeline(
            context,
            args.phase,
            skip_images=args.skip_images,
            default_password=args.default_password,
            force=args.force,
        )
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
