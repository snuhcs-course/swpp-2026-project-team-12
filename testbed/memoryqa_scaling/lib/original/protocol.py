"""Pure preparation: no Django, API clients, environment loading, or DB access."""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import random
import subprocess
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from .app_contract import episode_body, model_defaults, relationships, utc_time

CONDITIONS = ("current_post", "full_history", "graphiti")
CATEGORIES = ("current_state", "past_state_or_report", "entity_separation", "insufficient_information")
DATA_FILES = ("memory_posts.json", "probe_posts.json", "qa_runtime.json", "qa_gold.json",
              "summary_runtime.json", "summary_gold.json", "family.json", "family_metadata.json",
              "assets.json", "fact_catalog_gold.json")
PROMPT_NAMES = ("POST_SUMMARY", "POST_QA", "POST_QA_RETRIEVAL", "MAX_QUERIES", "FACT_BUDGET",
                "ANSWER_MAX_TOKENS", "DECISION_MAX_TOKENS")
QA_CHECKS = ("natural_question", "viewer_relationship", "answer_units", "evidence_entails_answer",
             "temporal_meaning", "answerability", "photo_reshare")
SUMMARY_CHECKS = ("atomic_text_facts", "visible_image_facts", "forbidden_inferences", "viewer_relationship")
DATASET_CHECKS = ("family_structure", "all_history_posts", "all_20_probe_posts", "background_has_no_conflicting_answers", "all_photos_match_captions", "fact_catalog_links_and_time_semantics")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def at(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("모든 시각에는 시간대가 필요합니다.")
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def dataset_counts(config):
    counts = config.get("dataset_counts", {"memory_posts": 100, "history_photo_posts": 40, "unique_photos": 40})
    require(set(counts) == {"memory_posts", "history_photo_posts", "unique_photos"}, "데이터 개수 설정 필드 오류")
    require(all(type(v) is int and v > 0 for v in counts.values()), "데이터 개수는 양의 정수여야 합니다.")
    require(counts["history_photo_posts"] == counts["unique_photos"] <= counts["memory_posts"], "사진/게시글 개수 설정 오류")
    return counts


def load_config(path):
    path = Path(path).resolve()
    config = read(path)
    dataset_counts(config)
    for key in ("dataset", "backend", "output"):
        config[key] = str((path.parent / config[key]).resolve())
    if config.get("shared_description_config"):
        config["shared_description_config"] = str((path.parent / config["shared_description_config"]).resolve())
    expected = {"repetitions": 3, "concurrency": 1, "max_queries": 5, "fact_budget": 5,
                "answer_max_tokens": 700, "decision_max_tokens": 1200, "image_detail": "high",
                "schema_version": 2, "protocol_id": "family-memory-app-eval-v2",
                "history_policy": "shared_frozen_app_photo_caption_descriptions",
                "relation_policy": "app_relationship_no_extra_family_metadata", "warmup_excluded": False,
                "description_max_tokens": 2000, "description_service_tier": None,
                "description_reasoning_effort": None,
                "timeout_seconds": 60, "sdk_max_retries": 1,
                "embedding_model": "text-embedding-3-small"}
    for key, value in expected.items():
        if config.get(key) != value:
            raise ValueError(f"공통 프로토콜 불일치: {key} (새 프로토콜 버전으로 변경하세요)")
    if not config.get("run_id") or not all(c.isalnum() or c in "-_" for c in config["run_id"]):
        raise ValueError("run_id에는 영문/숫자/하이픈/밑줄만 사용하세요.")
    return config


def prompt_snapshot(backend):
    tree = ast.parse((Path(backend) / "integrations/ai/prompts.py").read_text())
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in PROMPT_NAMES:
                    values[target.id] = ast.literal_eval(node.value)
    if set(values) != set(PROMPT_NAMES):
        raise ValueError("채택된 앱 프롬프트/한도를 찾을 수 없습니다.")
    return values


def backend_snapshot(config):
    backend = Path(config["backend"])
    head = subprocess.check_output(["git", "-C", str(backend), "rev-parse", "HEAD"], text=True).strip()
    require(head == config["backend_base_commit"], "앱 HEAD가 고정한 커밋과 다릅니다. 새 실험 버전이 필요합니다.")
    paths = sorted({p for folder in ("integrations", "apps", "configs")
                    for p in (backend / folder).rglob("*.py")} | {backend / "requirements.txt"})
    for path in paths:
        expected = subprocess.check_output(["git", "-C", str(backend), "show", f"{head}:backend/{path.relative_to(backend)}"])
        require(path.read_bytes() == expected, f"앱 파일이 고정 커밋과 다릅니다: {path.relative_to(backend)}")
    return {"head": head, "base": config["backend_base_commit"],
            "files": {str(p.relative_to(backend)): file_hash(p) for p in sorted(paths)}}


def load_dataset(config):
    root = Path(config["dataset"])
    data = {name: read(root / name) for name in DATA_FILES}
    memory, probes = data["memory_posts.json"], data["probe_posts.json"]
    counts = dataset_counts(config)
    qa, gold = data["qa_runtime.json"], data["qa_gold.json"]
    summaries, sgold = data["summary_runtime.json"], data["summary_gold.json"]
    require((len(memory), len(probes), len(qa), len(summaries)) == (counts["memory_posts"], 20, 40, 20), "설정한 과거 기록/20/40/20 개수 불일치")
    mem = {p["post_key"]: p for p in memory}
    probe_map = {p["post_key"]: p for p in probes}
    require(len(mem) == counts["memory_posts"] and len(probe_map) == 20 and not (mem.keys() & probe_map.keys()), "게시글 ID 중복")
    people = {m["key"]: m["name"] for m in data["family_metadata.json"]["members"]}
    require(len(people) == 4, "가족은 4명이어야 합니다.")
    relations = data["family_metadata.json"]["relationships"]
    require(len({(r["viewer"], r["target"]) for r in relations}) == 16, "16개 방향 관계가 필요합니다.")
    asset_map = {a["image_id"]: a for a in data["assets.json"]}
    image_hashes = {}
    from PIL import Image
    for post in memory + probes:
        require(post["author_key"] in people and len(post["caption"]) <= 2000, "작성자/본문 오류")
        at(post["created_at"])
        if post.get("image_path"):
            path = Path(post["image_path"])
            image_hashes[post["image_id"]] = file_hash(path)
            require(image_hashes[post["image_id"]] == asset_map[post["image_id"]]["sha256"], "사진 해시 불일치")
            with Image.open(path) as image:
                image.verify()
        else:
            require(post in memory, "평가 게시글의 사진 누락")
    require(len(image_hashes) == counts["unique_photos"], "설정한 서로 다른 원본 사진 수와 다릅니다.")
    require(len(asset_map) == len(data["assets.json"]) == counts["unique_photos"], "사진 원장 개수/중복 오류")
    require(sum(bool(p.get("image_path")) for p in memory) == counts["history_photo_posts"], "설정한 과거 사진 글 수와 다릅니다.")
    for post in probes:
        source = mem.get(post.get("reshared_from_post_key"))
        require(source is not None and source["image_id"] == post["image_id"], "재공유 사진의 원글 불일치")
        require(at(source["created_at"]) < at(post["created_at"]), "재공유 시간 오류")
    qids = {q["question_id"] for q in qa}
    gold_map = {g["question_id"]: g for g in gold}
    require(len(qids) == 40 and qids == set(gold_map), "질문/정답 ID 불일치")
    require(Counter(g["category"] for g in gold) == Counter({k: 10 for k in CATEGORIES}), "질문 유형 분포 오류")
    require(sum(g["evidence_metric_eligible"] for g in gold) == 30, "근거 평가 대상은 30개여야 합니다.")
    for q in qa:
        g = gold_map[q["question_id"]]
        require(q["current_post_key"] in probe_map and q["viewer_key"] in people, "질문 입력 연결 오류")
        require(0 < len(q["question"]) <= 1000 and bool(g["required_answer_units"]), "질문/핵심 정답 누락")
        require(at(q["asked_at"]) >= at(probe_map[q["current_post_key"]]["created_at"]), "질문이 글보다 빠릅니다.")
        require(at(g["question_time"]) == at(q["asked_at"]), "정답의 질문 시각 불일치")
        require(all(at(p["created_at"]) < at(q["asked_at"]) for p in memory), "질문 이후 과거 기록 존재")
        for group in g["sufficient_evidence_sets"]:
            require(bool(group) and set(group) <= mem.keys(), "충분 근거 ID 오류")
        for key in ("preferred_evidence_post_ids", "optional_evidence_post_ids", "must_filter_post_ids"):
            require(set(g[key]) <= mem.keys(), "정답 근거가 과거 기록에 없습니다.")
        require(not g["evidence_metric_eligible"] or bool(g["sufficient_evidence_sets"]), "필수 근거 조합 누락")
    require(Counter(q["current_post_key"] for q in qa) == Counter({k: 2 for k in probe_map}), "게시글당 질문 2개가 필요합니다.")
    require({s["current_post_key"] for s in summaries} == set(probe_map) == {s["post_key"] for s in sgold}, "요약 연결 오류")
    evaluated_q = config.get("evaluation_question_ids", [q["question_id"] for q in qa])
    evaluated_s = config.get("evaluation_summary_ids", [s["current_post_key"] for s in summaries])
    conditions = config.get("qa_conditions", list(CONDITIONS))
    require(len(evaluated_q) == len(set(evaluated_q)) and set(evaluated_q) <= qids and evaluated_q, "평가 질문 선택 오류")
    require(len(evaluated_s) == len(set(evaluated_s)) and set(evaluated_s) <= probe_map.keys(), "평가 요약 선택 오류")
    require(len(conditions) == len(set(conditions)) and set(conditions) <= set(CONDITIONS) and conditions, "평가 방식 선택 오류")
    if "evaluation_question_ids" in config:
        require(len(evaluated_q) == 20 and Counter(gold_map[k]["category"] for k in evaluated_q) == Counter({k:5 for k in CATEGORIES}), "공통 패널은 유형별 5개·20문항이어야 합니다.")
    require(set(config["pilot_question_ids"]) <= qids and len(config["pilot_question_ids"]) == 8, "예비 질문 오류")
    require(set(config["pilot_question_ids"]) <= set(evaluated_q), "예비 질문이 본 평가에 없습니다.")
    require(Counter(gold_map[k]["category"] for k in config["pilot_question_ids"]) == Counter({k: 2 for k in CATEGORIES}), "예비 질문 유형 오류")
    require(len(set(config["pilot_summary_ids"])) == (4 if evaluated_s else 0) and set(config["pilot_summary_ids"]) <= set(evaluated_s), "예비 요약 오류")
    # Legacy frozen datasets remain readable; revised fixtures carry an explicit gold-link schema.
    catalog_audit = None
    if any("evidence_assertions" in f for f in data["fact_catalog_gold.json"]):
        from .catalog_validation import validate_catalog
        catalog_audit = validate_catalog(data)
    hashes = {name: file_hash(root / name) for name in DATA_FILES}
    app_relations = relationships(config["backend"], data["family.json"])
    data.update(memory=mem, probes=probe_map, qa=qa, gold=gold_map,
                summaries=summaries, summary_gold={s["post_key"]: s for s in sgold}, people=people,
                dataset_fingerprint=digest({"files": hashes, "images": image_hashes}),
                file_hashes=hashes, image_hashes=image_hashes, app_relations=app_relations, catalog_audit=catalog_audit,
                evaluated_question_ids=evaluated_q, evaluated_summary_ids=evaluated_s, qa_conditions=conditions)
    return data


def relation(data, viewer, author):
    return data["app_relations"][viewer][author]


def history_records(data, descriptions=None):
    records = [{"id": p["post_key"], "작성자": data["people"][p["author_key"]],
                "원문": p["caption"], "게시시각": utc_time(p["created_at"])}
               for p in sorted(data["memory"].values(), key=lambda p: (at(p["created_at"]), p["post_key"]))]
    for record in records:
        if descriptions is not None:
            record.pop("원문")
            record["상세 설명"] = descriptions[record["id"]]["description"]
    return records


def seed_body(record):
    return episode_body(record["작성자"], record["상세 설명"])


def memory_plan(data):
    return [{**r, "image_path": data["memory"][r["id"]].get("image_path"),
             "image_sha256": data["image_hashes"].get(data["memory"][r["id"]].get("image_id"))}
            for r in history_records(data)]


def tasks(data, config, phase):
    rng = random.Random(config["random_seed"] + (1 if phase == "pilot" else 2))
    selected_q = [q for q in data["qa"] if q["question_id"] in data["evaluated_question_ids"] and (phase == "main" or q["question_id"] in config["pilot_question_ids"])]
    selected_s = [s for s in data["summaries"] if s["current_post_key"] in data["evaluated_summary_ids"] and (phase == "main" or s["current_post_key"] in config["pilot_summary_ids"])]
    rows = []
    for repeat in range(1, (config["repetitions"] if phase == "main" else 1) + 1):
        blocks = [("qa", q) for q in selected_q] + [("summary", s) for s in selected_s]
        rng.shuffle(blocks)
        for feature, case in blocks:
            conditions = list(data["qa_conditions"] if feature == "qa" else ("summary_direct",))
            rng.shuffle(conditions)
            for condition in conditions:
                post = data["probes"][case["current_post_key"]]
                when = case["asked_at"] if feature == "qa" else (at(post["created_at"]) + timedelta(minutes=1)).isoformat()
                payload = {"작성자": data["people"][post["author_key"]], "관계": relation(data, case["viewer_key"], post["author_key"]),
                           "원문": post["caption"], "게시시각": utc_time(post["created_at"])}
                case_id = case["question_id"] if feature == "qa" else post["post_key"]
                if feature == "qa":
                    payload.update(질문=case["question"], 질문자=data["people"][case["viewer_key"]],
                                   이전대화=[], 현재시각=utc_time(when))
                rows.append({"task_id": f"{phase}:{feature}:{case_id}:{condition}:{repeat}", "phase": phase,
                             "feature": feature, "case_id": case_id, "condition": condition, "repeat": repeat,
                             "current_post_key": post["post_key"], "viewer_key": case["viewer_key"],
                             "image_path": post["image_path"], "image_sha256": data["image_hashes"][post["image_id"]],
                             "as_of": when, "payload": payload})
    return rows


def review_template(data):
    rows = []
    for kind, cases in (("qa", data["evaluated_question_ids"]), ("summary", data["evaluated_summary_ids"])):
        checks = QA_CHECKS if kind == "qa" else SUMMARY_CHECKS
        rows.extend({"id": f"{kind}:{key}", "status": "pending", "reviewer": "", "notes": "",
                     "checks": {name: None for name in checks}} for key in cases)
    return {"dataset_fingerprint": data["dataset_fingerprint"], "dataset_reviewer": "",
            "dataset_checks": {key: None for key in DATASET_CHECKS}, "rows": rows}


def review_ready(review, data):
    expected = {r["id"]: r for r in review_template(data)["rows"]}
    actual = {r["id"]: r for r in review.get("rows", [])}
    return (review.get("dataset_fingerprint") == data["dataset_fingerprint"]
            and bool(review.get("dataset_reviewer", "").strip())
            and set(review.get("dataset_checks", {})) == set(DATASET_CHECKS)
            and all(v is True for v in review["dataset_checks"].values()) and len(review.get("rows", [])) == len(expected)
            and set(actual) == set(expected) and all(r.get("status") == "pass" and r.get("reviewer", "").strip()
                and set(r.get("checks", {})) == set(expected[k]["checks"])
                and all(v is True for v in r["checks"].values()) for k, r in actual.items()))


def freeze(config):
    data = load_dataset(config)
    prompts = prompt_snapshot(config["backend"])
    for name, key in (("MAX_QUERIES", "max_queries"), ("FACT_BUDGET", "fact_budget"),
                      ("ANSWER_MAX_TOKENS", "answer_max_tokens"), ("DECISION_MAX_TOKENS", "decision_max_tokens")):
        if prompts[name] != config[key]:
            raise ValueError(f"앱 프롬프트 한도 불일치: {name}")
    backend = backend_snapshot(config)
    defaults = model_defaults(config["backend"])
    for setting, key in (("POST_AI_MODEL", "model"), ("POST_AI_SERVICE_TIER", "service_tier"),
                         ("POST_AI_REASONING_EFFORT", "reasoning_effort"), ("GRAPHITI_MODEL", "graphiti_model"),
                         ("OPENAI_MODEL", "description_model")):
        require(defaults[setting] == config[key], f"앱 기본 모델 설정 불일치: {setting}")
    common = {k: v for k, v in config.items() if k not in {"dataset", "dataset_counts", "backend", "output", "run_id", "pilot_question_ids", "pilot_summary_ids", "evaluation_question_ids", "evaluation_summary_ids", "qa_conditions", "shared_description_config"}}
    common["backend_files"] = backend["files"]
    common["prompts"] = prompts
    tree = ast.parse((Path(config["backend"]) / "integrations/ai/feed_description.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "DESCRIPTION_INSTRUCTIONS" for t in n.targets))
    common["description_prompt"] = ast.literal_eval(node.value.func.value).strip()
    common["app_model_defaults"] = defaults
    common["evaluation_scope"] = "App memory ingestion and QA flow with frozen shared descriptions; no mobile upload/TTS/UI latency."
    common["metrics_version"] = "family-memory-metrics-v2"
    common["metric_definitions"] = {
        "answer_accuracy": "All required meaning units correct, no material false claims; system errors count as incorrect.",
        "evidence_coverage": "Manual check that actual final memory context contains sufficient facts, not merely source IDs; eligible responses only; null until reviewed.",
        "source_post_coverage": "Automatic sufficient source-post ID set coverage after final context budgeting; does not prove a generated description preserved the needed fact.",
        "memory_update_error_rate": "Old state falsely asserted as current / current-state responses; safe abstention is an accuracy failure, not a stale claim.",
        "filtering_error_rate": "Wrong target/entity facts asserted / entity-separation responses.",
        "unsupported_answer_rate": "Invented answer / insufficient-information responses.",
        "tokens_per_question": "All observed generation input+output across decision, answer and internal reranking / planned tasks; embeddings and ingestion separate; null if incomplete.",
        "tokens_per_correct_answer": "Same total generation tokens / correct responses; null if no correct responses or incomplete usage/grading.",
        "setup_cost": "Photo/caption description generation and graph construction counted separately from QA. Full history and Graphiti both attribute the same one-time description cost; Graphiti also attributes graph construction. Include amortized setup+QA generation tokens per planned question; embeddings separate.",
        "latency": "Task wall time, including retries and errors, first calls retained; mean and nearest-rank P95.",
        "summary": "Macro text/image fact coverage; unsupported-claim response rate. Semantic paraphrases accepted.",
        "not_evaluated": "No injection robustness or dedicated relationship accuracy claim without a dedicated case set."}
    packages = {}
    for name in ("openai", "graphiti-core", "neo4j", "Django", "Pillow"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    common["packages"] = packages
    runner_files = {p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py")) if not p.name.startswith("test_")}
    identity = {"config": config, "dataset_fingerprint": data["dataset_fingerprint"],
                "backend_files": backend["files"], "packages": packages, "runner_files": runner_files}
    if config.get("shared_description_config"):
        identity["shared_description_config_hash"] = file_hash(config["shared_description_config"])
    return data, {"signature": digest(identity), "dataset_fingerprint": data["dataset_fingerprint"],
                  "config": config, "backend": backend, "packages": packages, "prompts": prompts,
                  "common_protocol": common, "common_protocol_hash": digest(common),
                  "files": data["file_hashes"], "images": data["image_hashes"],
                  "family_id": 900000000 + int(digest(config["run_id"])[:10], 16) % 100000000}


def prepare(config):
    data, lock = freeze(config)
    output = Path(config["output"])
    lock_path = output / "prepared/lock.json"
    if lock_path.exists() and read(lock_path)["signature"] != lock["signature"]:
        raise ValueError("기존 실행 조건/데이터/코드가 바뀌었습니다. 새 run_id와 output을 사용하세요.")
    save(lock_path, lock)
    save(output / "prepared/common_protocol.json", lock["common_protocol"])
    for phase in ("pilot", "main"):
        save(output / f"prepared/tasks_{phase}.json", tasks(data, config, phase))
    save(output / "prepared/seed_plan.json", memory_plan(data))
    save(output / "prepared/app_relationships.json", data["app_relations"])
    if not (output / "review/dataset_review.json").exists():
        save(output / "review/dataset_review.json", review_template(data))
    if not (output / "review/team_agreement.json").exists():
        save(output / "review/team_agreement.json", {"status": "pending", "reviewers": [], "notes": "",
             "common_protocol_hash": lock["common_protocol_hash"]})
    if not (output / "review/pilot_acceptance.json").exists():
        save(output / "review/pilot_acceptance.json", {"status": "pending", "reviewer": "", "notes": "",
             "signature": lock["signature"]})
    return data, lock


def verify_prepared(config):
    data, current = freeze(config)
    output = Path(config["output"])
    saved = read(output / "prepared/lock.json")
    if saved["signature"] != current["signature"]:
        raise ValueError("입력/코드/설정/패키지가 준비 시점과 다릅니다. 새 실험 버전이 필요합니다.")
    for phase in ("pilot", "main"):
        if read(output / f"prepared/tasks_{phase}.json") != tasks(data, config, phase):
            raise ValueError("실행 계획이 변경되었습니다.")
    if read(output / "prepared/seed_plan.json") != memory_plan(data):
        raise ValueError("기억 적재 입력이 변경되었습니다.")
    if read(output / "prepared/app_relationships.json") != data["app_relations"]:
        raise ValueError("앱 관계 계산표가 변경되었습니다.")
    if read(output / "prepared/common_protocol.json") != saved["common_protocol"]:
        raise ValueError("공통 프로토콜 파일이 변경되었습니다.")
    return data, saved


def readiness(config):
    data, lock = verify_prepared(config)
    output = Path(config["output"])
    reviewed = review_ready(read(output / "review/dataset_review.json"), data)
    agreement = read(output / "review/team_agreement.json")
    agreed = (agreement.get("status") == "confirmed" and len(set(agreement.get("reviewers", []))) >= 2
              and all(str(x).strip() for x in agreement["reviewers"])
              and agreement.get("common_protocol_hash") == lock["common_protocol_hash"])
    return {"offline_ready": True, "dataset_review_complete": bool(reviewed), "team_protocol_confirmed": bool(agreed),
            "dataset": str(config["dataset"]), "dataset_fingerprint": data["dataset_fingerprint"],
            "catalog_audit": data.get("catalog_audit"),
            "live_dependencies_installed": all(lock["packages"].values()),
            "paid_execution_enabled": False,
            "unverified": ["API access/model availability", "Neo4j connectivity and empty experiment group", "live description and answer quality"],
            "app_commit": lock["backend"]["head"], "common_protocol_hash": lock["common_protocol_hash"],
            "memory_descriptions_generated": (output / "descriptions.json").exists(),
            "counts": {**dataset_counts(config), "probe_posts": 20, "question_bank": 40, "summary_bank": 20,
                       "questions": len(data["evaluated_question_ids"]), "summaries": len(data["evaluated_summary_ids"]),
                       "pilot_tasks": len(tasks(data, config, "pilot")), "main_tasks": len(tasks(data, config, "main"))},
            "group_id": f"family_{lock['family_id']}", "signature": lock["signature"]}
