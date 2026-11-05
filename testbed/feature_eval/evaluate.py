"""Evaluate five AI features against a dataset whose test DB testbed.pipeline has prepared.

Each feature writes testbed/output/<dataset>/feature_eval/<feature>.json with the raw output,
rule-based checks, and optional LLM judge verdicts for every case.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from ..common.labels import establishes_map, retrieved_feed_keys
from ..common.paths import BACKEND_ROOT, config_relative, read_json, write_json
from ..common.run_context import PipelineContext, load_database_state, load_pipeline_state
from . import checks
from .cases import FEATURES, build_cases
from .judge import Judge, judge_images, judge_material

# The pipeline phase each feature needs before it can run.
REQUIRES = {
    "description": "seed-memory",
    "summary": "seed-memory",
    "digest": "seed-memory",
    "post_qa": "seed-probes",
    "stt": "construct",
}
LEAK_KEYS = {"forbidden_strings", "filter_leaked", "other_day_caption_copied"}


def load_gold(context):
    """Optional per-feature answers stored next to the dataset config."""
    path = config_relative(context.config, "gold.json")
    return read_json(path) if path.is_file() else {}


def load_thresholds(context):
    path = config_relative(context.config, "thresholds.json")
    return read_json(path) if path.is_file() else {}


def missing_requirements(features, completed):
    return {feature: REQUIRES[feature] for feature in features if REQUIRES[feature] not in completed}


def score(feature, case, output, manifest, post_ids):
    if feature == "description":
        return checks.check_description(case, output)
    if feature == "summary":
        return checks.check_summary(case, output)
    if feature == "digest":
        return checks.check_digest(case, output)
    if feature == "stt":
        return checks.check_stt(case, output)
    retrieved = retrieved_feed_keys(output.get("memories", []), post_ids)
    return checks.check_post_qa(case, output, retrieved, establishes_map(manifest))


def aggregate(rows):
    """Mean of every bool/number check, rate of non-empty leak lists, and pass rate per judge criterion."""
    scored = [row for row in rows if "error" not in row]
    values, judged = {}, {}
    for row in scored:
        for key, value in row["checks"].items():
            if key in LEAK_KEYS:
                values.setdefault(f"{key}_rate", []).append(bool(value))
            elif isinstance(value, (bool, int, float)):
                values.setdefault(key, []).append(float(value))
        for criterion, verdict in (row.get("judge") or {}).get("verdicts", {}).items():
            judged.setdefault(criterion, []).append(verdict["pass"])
    metrics = {"case_count": len(rows), "error_count": len(rows) - len(scored)}
    metrics.update({key: sum(items) / len(items) for key, items in sorted(values.items())})
    metrics.update({f"judge_{key}_pass_rate": sum(items) / len(items) for key, items in sorted(judged.items())})
    if judged:
        verdict_sets = [row["judge"]["verdicts"] for row in scored if row.get("judge")]
        metrics["judge_all_pass_rate"] = sum(all(v["pass"] for v in verdicts.values())
                                             for verdicts in verdict_sets) / len(verdict_sets)
    return metrics


def metrics_by_type(rows):
    """Per-category metrics for cases that declare a type, such as STT relay/negation/misheard."""
    groups = {}
    for row in rows:
        if row["case"].get("type"):
            groups.setdefault(row["case"]["type"], []).append(row)
    return {kind: aggregate(group) for kind, group in groups.items()} or None


def check_thresholds(metrics, spec):
    """spec: {metric: {"operator": ">=" | "<=", "target": number, "rationale": str}}."""
    results = {}
    for metric, rule in spec.items():
        actual, operator, target = metrics.get(metric), rule["operator"], rule["target"]
        if operator not in {">=", "<="}:
            raise ValueError(f"지원하지 않는 threshold operator입니다: {operator}")
        passed = actual is not None and (actual >= target if operator == ">=" else actual <= target)
        results[metric] = {"actual": actual, "operator": operator, "target": target,
                           "passed": passed, "rationale": rule.get("rationale", "")}
    return results


def format_value(value):
    if isinstance(value, dict) and "mean" in value:
        value = value["mean"]
    if isinstance(value, bool) or value is None:
        return str(value)
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def format_results(feature, metrics, threshold_results=None):
    """Lines printed after each feature: every metric, then each declared threshold with PASS/FAIL."""
    lines = [f"[{feature}] metrics"]
    lines += [f"  {key}: {format_value(value)}" for key, value in metrics.items()]
    if threshold_results:
        passed = sum(result["passed"] for result in threshold_results.values())
        lines.append(f"[{feature}] thresholds {passed}/{len(threshold_results)} passed")
        lines += [f"  {'PASS' if result['passed'] else 'FAIL'}  {metric} = {format_value(result['actual'])}"
                  f" (target {result['operator']} {result['target']})"
                  for metric, result in threshold_results.items()]
    return lines


def previous_outputs(report_path):
    if not report_path.is_file():
        return {}
    return {row["case"]["id"]: row["output"] for row in read_json(report_path)["cases"] if "output" in row}


def evaluate_feature(feature, cases, *, manifest, post_ids, family_id, posts, output_root, judge,
                     thresholds=None, reuse_outputs=False, regenerate_descriptions=False, log=print):
    from .runners import RUNNERS

    report_path = output_root / "feature_eval" / f"{feature}.json"
    reused = previous_outputs(report_path) if reuse_outputs else {}
    rows = []
    for index, case in enumerate(cases, 1):
        row = {"case": case}
        try:
            if case["id"] in reused:
                output = reused[case["id"]]
            else:
                output = RUNNERS[feature](case, posts=posts, family_id=family_id,
                                          regenerate=regenerate_descriptions)
            row["output"] = output
            row["checks"] = score(feature, case, output, manifest, post_ids)
            if judge:
                row["judge"] = judge.evaluate(feature, case, output, judge_material(feature, case, output),
                                              judge_images(feature, case, output_root))
        except Exception as error:  # one failing case must not lose the rest of a paid run
            row["error"] = f"{type(error).__name__}: {error}"
        rows.append(row)
        if "error" in row:  # successful cases stay quiet; only failures are worth a line
            log(f"  [{feature}] {index}/{len(cases)} {case['id']} 오류: {row['error']}")

    metrics = aggregate(rows)
    if feature == "post_qa":
        metrics["answer_diversity"] = checks.answer_diversity(rows)
    report = {
        "schema_version": 1,
        "feature": feature,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "judge_model": judge.model if judge else None,
        "metrics": metrics,
        "metrics_by_type": metrics_by_type(rows),
        "thresholds": check_thresholds(metrics, thresholds) if thresholds else None,
        "cases": rows,
    }
    write_json(report_path, report)
    return report_path, metrics


def plan_cases(features, manifest, gold, post_ids, limit=None):
    return {feature: build_cases(feature, manifest, gold, post_ids)[:limit] for feature in features}


def run(args):
    context = PipelineContext.create(args.dataset, output=args.output, backend=args.backend)
    manifest = read_json(context.manifest)
    database_state = load_database_state(context)
    post_ids = database_state["post_ids"]
    features = list(FEATURES) if "all" in args.feature else list(dict.fromkeys(args.feature))

    missing = missing_requirements(features, load_pipeline_state(context)["completed"])
    if missing and not args.force:
        raise RuntimeError("먼저 python -m testbed.pipeline으로 필요한 phase를 실행하세요: "
                           + ", ".join(f"{feature} → {phase}" for feature, phase in missing.items()))

    plan = plan_cases(features, manifest, load_gold(context), post_ids, args.limit)
    for feature, cases in plan.items():
        print(f"{feature}: {len(cases)}개 case")
    if args.dry_run:
        return {}

    thresholds = load_thresholds(context)
    adapter = context.adapter()
    results, checked, judge = {}, {}, None
    try:
        adapter.setup()
        from .runners import load_posts

        # Django settings load the repository .env, so the judge reads its key and model after setup.
        judge = None if args.no_judge else Judge(context.output / "feature_eval" / "judge_cache",
                                                 model=args.judge_model)
        posts = load_posts(post_ids)
        for feature, cases in plan.items():
            _, metrics = evaluate_feature(
                feature, cases, manifest=manifest, post_ids=post_ids, family_id=database_state["family_id"],
                posts=posts, output_root=context.output, judge=judge, thresholds=thresholds.get(feature),
                reuse_outputs=args.reuse_outputs, regenerate_descriptions=args.regenerate_descriptions,
            )
            results[feature] = metrics
            declared = thresholds.get(feature)
            checked[feature] = check_thresholds(metrics, declared) if declared else None
            print("\n".join(format_results(feature, metrics, checked[feature])))
    finally:
        adapter.close()
    if judge:
        print(f"judge 호출 {judge.calls}회 (나머지는 캐시)")
    all_checks = [result for feature_checks in checked.values() if feature_checks
                  for result in feature_checks.values()]
    if all_checks:
        print(f"threshold 전체: {sum(result['passed'] for result in all_checks)}/{len(all_checks)} 통과")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="datasets/ 아래 폴더 이름 또는 config 경로")
    parser.add_argument("--output", help="pipeline output 폴더. 기본값: testbed/output/<dataset_name>")
    parser.add_argument("--backend", default=str(BACKEND_ROOT))
    parser.add_argument("--feature", action="append", required=True, choices=(*FEATURES, "all"))
    parser.add_argument("--limit", type=int, help="기능마다 앞에서부터 N개 case만 실행")
    parser.add_argument("--dry-run", action="store_true", help="case 수만 출력하고 API는 호출하지 않음")
    parser.add_argument("--no-judge", action="store_true", help="규칙 기반 채점만 실행")
    parser.add_argument("--judge-model", help="기본값: JUDGE_AI_MODEL, 없으면 DEFAULT_AI_MODEL")
    parser.add_argument("--reuse-outputs", action="store_true", help="이전 보고서의 기능 출력을 재사용하고 채점만 다시 실행")
    parser.add_argument("--regenerate-descriptions", action="store_true", help="저장된 description 대신 새로 생성")
    parser.add_argument("--force", action="store_true", help="pipeline phase 확인을 건너뜀")
    args = parser.parse_args()
    try:
        run(args)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
