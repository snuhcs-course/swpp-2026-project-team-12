"""Measure search-query quality separately from the answer, using queries already saved in a report.

The feature reports keep only the memories left after post_flow.select_budget, so a low recall there
cannot tell a weak query from a good query whose hits were cut. This re-runs only the Graphiti search
for each saved query (embedding calls, no LLM) and compares three things per post_qa case:

- raw recall: required labels reachable from the model's queries before the budget cut
- budget recall: what the answer model actually received (from the post_qa report)
- question baseline: raw recall when the user's question itself is the only query

For STT it checks whether searching would have surfaced the right name or word for `misheard` and
`misheard_word` cases.
Writes testbed/output/<dataset>/feature_eval/queries.json.
"""
from __future__ import annotations

import argparse
import asyncio
import re
from collections import Counter

from ..common.labels import establishes_map, labels_for, retrieved_feed_keys
from ..common.paths import BACKEND_ROOT, read_json, write_json
from ..common.run_context import PipelineContext, load_database_state

META_WORDS = ("작성자", "게시글", "게시물", "기록", "확인해", "알려", "찾아", "주세요")
MAX_QUERIES = 5


def ratio(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def ranked_hits(memories, post_ids):
    """Feed keys in retrieval order, split by whether they came from a fact or a direct episode hit."""
    by_name = {f"post_{post_id}": key for key, post_id in post_ids.items()}
    order, kinds = [], {}
    for memory in memories:
        kind = "episode" if memory.get("source_episode_ids") == [memory.get("id")] else "fact"
        for source in memory.get("sources", []):
            key = by_name.get(source.get("name"))
            if key:
                if key not in order:
                    order.append(key)
                kinds.setdefault(key, set()).add(kind)
    return order, kinds


def query_features(query, case):
    names = [case["author_name"], case["viewer_name"]]
    return {
        "length": len(query),
        "meta_words": [word for word in META_WORDS if word in query],
        "mentions_author_or_viewer": any(name and name in query for name in names),
    }


def score_query(query, memories, case, establishes, post_ids):
    required = set(case.get("required_memories", []))
    order, kinds = ranked_hits(memories, post_ids)
    hits = [key for key in order if establishes.get(key, set()) & required]
    return {
        "query": query,
        **query_features(query, case),
        "retrieved": order,
        "required_hit_keys": hits,
        "required_hit": bool(hits),
        "first_required_rank": order.index(hits[0]) + 1 if hits else None,
        "hit_only_via_episode": bool(hits) and all(kinds[key] == {"episode"} for key in hits),
    }


def recall(keys, case, establishes):
    required = set(case.get("required_memories", []))
    return len(required & labels_for(keys, establishes)) / len(required) if required else None


async def search_all(queries, family_id):
    """One raw search per distinct query; never more than MAX_QUERIES per call, as in the app."""
    from integrations.ai_workers.graphiti_client import close_graphiti, create_graphiti
    from integrations.ai_workers.searching_graphiti import search_many

    graphiti = create_graphiti()
    results = {}
    try:
        pending = list(dict.fromkeys(queries))
        for start in range(0, len(pending), MAX_QUERIES):
            batch = pending[start:start + MAX_QUERIES]
            for result in await search_many(graphiti, family_id, batch, max_queries=MAX_QUERIES):
                results[result["query"]] = result["memories"]
    finally:
        await close_graphiti(graphiti)
    return results


def analyze_post_qa(rows, raw, establishes, post_ids):
    cases = []
    for row in rows:
        if "error" in row:
            continue
        case, output = row["case"], row["output"]
        queries = output.get("queries") or []
        scored = [score_query(query, raw[query], case, establishes, post_ids) for query in queries]
        union = list(dict.fromkeys(key for item in scored for key in item["retrieved"]))
        baseline_keys, _ = ranked_hits(raw[case["question"]], post_ids)
        verdict = (row.get("judge") or {}).get("verdicts", {}).get("queries_fit")
        cases.append({
            "id": case["id"],
            "feed_key": case["feed_key"],
            "question": case["question"],
            "required_count": len(case.get("required_memories", [])),
            "query_count": len(queries),
            "raw_recall": recall(union, case, establishes) if queries else None,
            "budget_recall": row["checks"].get("required_recall"),
            "question_baseline_recall": recall(baseline_keys, case, establishes),
            "judge_queries_fit": verdict["pass"] if verdict else None,
            "queries": scored,
        })
    for item in cases:
        item["lost_to_budget"] = (item["raw_recall"] or 0) > (item["budget_recall"] or 0)
    all_queries = [query for item in cases for query in item["queries"]]
    multi = [item for item in cases if item["required_count"] > 1]
    metrics = {
        "case_count": len(cases),
        "query_count_mean": ratio([item["query_count"] for item in cases]),
        "query_count_distribution": dict(sorted(Counter(item["query_count"] for item in cases).items())),
        "raw_recall": ratio([item["raw_recall"] for item in cases]),
        "budget_recall": ratio([item["budget_recall"] for item in cases]),
        "question_baseline_recall": ratio([item["question_baseline_recall"] for item in cases]),
        "lost_to_budget_rate": ratio([item["lost_to_budget"] for item in cases]),
        "queries_beat_baseline_rate": ratio([(item["raw_recall"] or 0) > (item["question_baseline_recall"] or 0)
                                             for item in cases]),
        "queries_below_baseline_rate": ratio([(item["raw_recall"] or 0) < (item["question_baseline_recall"] or 0)
                                              for item in cases]),
        "multi_part_cases": len(multi),
        "multi_part_fewer_queries_than_parts": ratio([item["query_count"] < item["required_count"] for item in multi]),
        "multi_part_raw_recall": ratio([item["raw_recall"] for item in multi]),
        "per_query_required_hit_rate": ratio([query["required_hit"] for query in all_queries]),
        "per_query_first_required_rank": ratio([query["first_required_rank"] for query in all_queries]),
        "hit_only_via_episode_rate": ratio([query["hit_only_via_episode"] for query in all_queries
                                            if query["required_hit"]]),
        "query_length_mean": ratio([query["length"] for query in all_queries]),
        "queries_with_meta_words_rate": ratio([bool(query["meta_words"]) for query in all_queries]),
        "meta_word_hit_rate": ratio([query["required_hit"] for query in all_queries if query["meta_words"]]),
        "plain_query_hit_rate": ratio([query["required_hit"] for query in all_queries if not query["meta_words"]]),
        "judge_queries_fit_pass_rate": ratio([item["judge_queries_fit"] for item in cases]),
    }
    by_post = {}
    for item in cases:
        by_post.setdefault(item["feed_key"], []).append(item)
    per_post = {key: {
        "raw_recall": ratio([item["raw_recall"] for item in items]),
        "budget_recall": ratio([item["budget_recall"] for item in items]),
        "question_baseline_recall": ratio([item["question_baseline_recall"] for item in items]),
        "query_counts": [item["query_count"] for item in items],
    } for key, items in by_post.items()}
    return {"metrics": metrics, "per_post": per_post, "cases": cases}


def text_of(memories):
    return " ".join([memory.get("fact", "") for memory in memories]
                    + [source.get("text", "") for memory in memories for source in memory.get("sources", [])])


def analyze_stt(rows, raw):
    """For misheard names and words: would a search on the recognized text have shown the correct one?"""
    cases = []
    for row in rows:
        if "error" in row:
            continue
        case, output = row["case"], row["output"]
        item = {"id": case["id"], "type": case.get("type"), "searched": bool(output.get("query")),
                "queries": output.get("queries") or []}
        if case.get("type") in {"misheard", "misheard_word"}:
            found = text_of(raw[case["recognized"]])
            wrong = [value for value in case.get("must_remove", []) if value]
            right = [value for value in case.get("must_keep", []) if value and not re.fullmatch(r"\d+", value)]
            item.update({
                "probe_query": case["recognized"],
                "correct_name_in_results": all(value in found for value in right),
                "misheard_name_in_results": any(value in found for value in wrong),
            })
        cases.append(item)
    misheard = [item for item in cases if item["type"] in {"misheard", "misheard_word"}]
    metrics = {
        "case_count": len(cases),
        "searched_rate": ratio([item["searched"] for item in cases]),
        "misheard_searched_rate": ratio([item["searched"] for item in misheard]),
        "misheard_correct_name_reachable_rate": ratio([item["correct_name_in_results"] for item in misheard]),
    }
    return {"metrics": metrics, "cases": cases}


def run(args):
    context = PipelineContext.create(args.dataset, output=args.output, backend=args.backend)
    manifest = read_json(context.manifest)
    database_state = load_database_state(context)
    post_ids, family_id = database_state["post_ids"], database_state["family_id"]
    establishes = establishes_map(manifest)
    report_dir = context.output / "feature_eval"
    reports = {feature: read_json(report_dir / f"{feature}.json")["cases"]
               for feature in ("post_qa", "stt") if (report_dir / f"{feature}.json").is_file()}
    if not reports:
        raise FileNotFoundError("먼저 feature_eval로 post_qa 또는 stt 보고서를 만드세요.")

    queries = []
    for row in reports.get("post_qa", []):
        if "error" not in row:
            queries += (row["output"].get("queries") or []) + [row["case"]["question"]]
    for row in reports.get("stt", []):
        if "error" not in row:
            queries += row["output"].get("queries") or []
            if row["case"].get("type") in {"misheard", "misheard_word"}:
                queries.append(row["case"]["recognized"])

    adapter = context.adapter()
    try:
        adapter.setup()
        raw = asyncio.run(search_all(queries, family_id))
    finally:
        adapter.close()

    report = {"schema_version": 1}
    if "post_qa" in reports:
        report["post_qa"] = analyze_post_qa(reports["post_qa"], raw, establishes, post_ids)
    if "stt" in reports:
        report["stt"] = analyze_stt(reports["stt"], raw)
    path = report_dir / "queries.json"
    write_json(path, report)
    for feature in ("post_qa", "stt"):
        if feature in report:
            print(f"[{feature}]")
            for key, value in report[feature]["metrics"].items():
                print(f"  {key}: {round(value, 3) if isinstance(value, float) else value}")
    print(path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="datasets/ 아래 폴더 이름 또는 config 경로")
    parser.add_argument("--output", help="pipeline output 폴더. 기본값: testbed/output/<dataset_name>")
    parser.add_argument("--backend", default=str(BACKEND_ROOT))
    args = parser.parse_args()
    try:
        run(args)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
