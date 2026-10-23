"""Paid phases. Imported only after explicit CLI opt-in and offline review gates."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from .protocol import digest, file_hash, history_records, load_config, read, save, seed_body, verify_prepared
from .usage import capture, instrument_sdk, totals


def append(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def bootstrap(config, *, require_graph=True):
    backend = Path(config["backend"])
    output = Path(config["output"])
    if os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") != "https://api.openai.com/v1":
        raise ValueError("이 프로토콜은 api.openai.com만 사용합니다.")
    sys.path.insert(0, str(backend))
    os.environ["DJANGO_SETTINGS_MODULE"] = "configs.settings"
    os.environ["DJANGO_DB_PATH"] = str(output / "test.sqlite3")
    os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
    # Process settings take precedence over .env. Never copy keys to experiment files.
    for name, key in (("POST_AI_MODEL", "model"), ("POST_AI_SERVICE_TIER", "service_tier"),
                      ("POST_AI_REASONING_EFFORT", "reasoning_effort"), ("GRAPHITI_MODEL", "graphiti_model"),
                      ("OPENAI_MODEL", "description_model")):
        os.environ[name] = str(config[key])
    import django
    from django.conf import settings
    django.setup()
    if Path(settings.BASE_DIR).resolve() != backend.resolve():
        raise ValueError("이미 다른 앱의 Django 설정이 로드되어 있습니다.")
    for name, key in (("POST_AI_MODEL", "model"), ("POST_AI_SERVICE_TIER", "service_tier"),
                      ("POST_AI_REASONING_EFFORT", "reasoning_effort"), ("GRAPHITI_MODEL", "graphiti_model"),
                      ("OPENAI_MODEL", "description_model")):
        if getattr(settings, name) != config[key]:
            raise ValueError(f"실제 앱 모델 설정 불일치: {name}")
    if os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") != "https://api.openai.com/v1":
        raise ValueError(".env에서 api.openai.com 외의 API 주소를 지정했습니다.")
    settings.MEDIA_ROOT = output / "media"
    if Path(settings.DATABASES["default"]["NAME"]).resolve() != (output / "test.sqlite3").resolve():
        raise ValueError("실험 전용 DB가 아닙니다.")
    if not settings.OPENAI_API_KEY or (require_graph and not settings.NEO4J_PASSWORD):
        raise ValueError("OPENAI_API_KEY와 NEO4J_PASSWORD 설정이 필요합니다. 값은 보고서에 기록하지 않습니다.")


def seed_sql(config, data, lock):
    """Create an isolated app DB, preserving all caption-only history posts."""
    from django.core.management import call_command
    from django.core.files import File
    from django.contrib.auth.hashers import make_password
    from django.db import transaction
    from apps.accounts.models import User
    from apps.families.models import FamilyRoom, Membership
    from apps.posts.models import Post
    path = Path(config["output"]) / "db_import.json"
    if path.exists():
        report = read(path)
        if report["signature"] != lock["signature"]:
            raise ValueError("DB 적재 조건 불일치")
        frozen_path = Path(config["output"]) / "descriptions.json"
        frozen_descriptions = ({r["post_key"]: r["description"] for r in read(frozen_path)["records"]}
                               if frozen_path.exists() else None)
        for key, pk in report["post_ids"].items():
            expected = (data["memory"] | data["probes"])[key]
            post = Post.objects.select_related("author").prefetch_related("photos").get(pk=pk, room_id=lock["family_id"])
            if (post.caption != expected["caption"] or post.created_at != datetime.fromisoformat(expected["created_at"])
                    or post.author.username != f"{config['run_id']}_{expected['author_key']}"):
                raise ValueError("적재한 게시글 내용/시간이 변경되었습니다.")
            files = post.photo_files()
            if expected.get("image_path"):
                if len(files) != 1 or file_hash(files[0].path) != data["image_hashes"][expected["image_id"]]:
                    raise ValueError("SQL 사진이 원본과 다릅니다.")
            elif files:
                raise ValueError("텍스트 게시글에 사진이 추가되었습니다.")
            if frozen_descriptions is not None and post.description != frozen_descriptions.get(key, ""):
                raise ValueError("SQL 설명이 동결한 설명과 다릅니다.")
        from apps.families.services import relationship
        users = {m["key"]: User.objects.get(username=f"{config['run_id']}_{m['key']}") for m in data["family.json"]["members"]}
        room = FamilyRoom.objects.get(pk=lock["family_id"])
        for member in data["family.json"]["members"]:
            u = users[member["key"]]
            if (u.display_name != member["name"] or u.gender != member["gender"]
                    or Membership.objects.get(room=room, user=u).slot != member["slot"]):
                raise ValueError("SQL 가족 구성원이 변경되었습니다.")
        if {v: {a: relationship(viewer, author, room) for a, author in users.items()}
                for v, viewer in users.items()} != data["app_relations"]:
            raise ValueError("실제 앱과 준비한 가족 관계 계산이 다릅니다.")
        return report
    call_command("migrate", interactive=False, verbosity=0)
    if FamilyRoom.objects.exists() or User.objects.exists() or Post.objects.exists():
        raise ValueError("새 실행에는 비어 있는 실험 전용 DB가 필요합니다.")
    with transaction.atomic():
        users = {}
        for member in data["family.json"]["members"]:
            user = User(username=f"{config['run_id']}_{member['key']}", display_name=member["name"], gender=member["gender"])
            user.set_unusable_password()
            user.save()
            users[member["key"]] = user
        room = FamilyRoom.objects.create(pk=lock["family_id"], name=config["run_id"], owner=users["jimin"],
                                         invite_code="MQ" + digest(config["run_id"])[:4].upper(), password_hash=make_password(None))
        for member in data["family.json"]["members"]:
            Membership.objects.create(room=room, user=users[member["key"]], slot=member["slot"])
        ids = {}
        for spec in [*data["memory"].values(), *data["probes"].values()]:
            post = Post(room=room, author=users[spec["author_key"]], caption=spec["caption"])
            if spec.get("image_path"):
                with Path(spec["image_path"]).open("rb") as handle:
                    post.image.save(Path(spec["image_path"]).name, File(handle), save=False)
            post.save()
            Post.objects.filter(pk=post.pk).update(created_at=spec["created_at"])
            ids[spec["post_key"]] = post.pk
    report = {"signature": lock["signature"], "family_id": lock["family_id"], "post_ids": ids,
              "memory_count": len(data["memory"]), "probe_count": len(data["probes"]), "graph_seed_scope": "only memory IDs; no automatic construction worker"}
    save(path, report)
    return report


async def graph_fingerprint(graphiti, group_id):
    nodes, _, _ = await graphiti.driver.execute_query(
        "MATCH (n {group_id:$g}) RETURN properties(n) AS p,labels(n) AS labels ORDER BY n.uuid", g=group_id, routing_="r")
    edges, _, _ = await graphiti.driver.execute_query(
        "MATCH (n {group_id:$g})-[r]->(m) RETURN n.uuid AS a,m.uuid AS b,type(r) AS kind,properties(r) AS p "
        "ORDER BY a,b,kind,r.uuid", g=group_id, routing_="r")
    return digest(json.loads(json.dumps({"nodes": [dict(r) for r in nodes], "edges": [dict(r) for r in edges]}, default=str)))


async def graph_episodes(graphiti, group):
    rows, _, _ = await graphiti.driver.execute_query(
        "MATCH (e:Episodic {group_id:$g}) RETURN e.name AS name,e.content AS text", g=group, routing_="r")
    result = {r["name"]: r["text"] for r in rows}
    if len(rows) != len(result):
        raise ValueError("Graphiti source 이름 중복")
    return result


def expected_sources(data, db):
    return {f"post_{db['post_ids'][r['id']]}": {"post_key": r["id"], "text": seed_body(r)}
            for r in history_records(data, data["descriptions"])}


def description_snapshot(config, data, db, lock):
    """Validate generated memory independently of the pre-generation input lock."""
    path = Path(config["output"]) / "descriptions.json"
    if not path.exists():
        raise ValueError("describe 단계에서 과거 게시글 전체 설명을 먼저 생성·동결하세요.")
    snapshot = read(path)
    if (snapshot.get("status") != "complete" or snapshot.get("signature") != lock["signature"]
            or snapshot.get("db_ids_hash") != digest(db["post_ids"])
            or snapshot.get("records_hash") != digest(snapshot.get("records", []))):
        raise ValueError("동결한 사진·본문 설명이 없거나 변경되었습니다.")
    records = snapshot["records"]
    mapped = {r["post_key"]: r for r in records}
    if len(records) != len(data["memory"]) or set(mapped) != set(data["memory"]):
        raise ValueError("과거 설명은 설정한 과거 게시글 전체만 포함해야 합니다.")
    raw = Path(config["output"]) / "descriptions.jsonl"
    logged = [json.loads(line) for line in raw.read_text().splitlines()]
    if (len(logged) != len(data["memory"]) or len({r["post_key"] for r in logged}) != len(data["memory"])
            or any(r.get("status") != "complete" or r.get("signature") != lock["signature"]
                   or r.get("description") != mapped[r["post_key"]]["description"] for r in logged)):
        raise ValueError("상세 설명 원시 호출 로그와 동결 내용이 다릅니다.")
    for key, record in mapped.items():
        if (not isinstance(record["description"], str) or not record["description"].strip()
                or set(record) != {"post_key", "description"}):
            raise ValueError("상세 설명 형식이 올바르지 않습니다.")
    data["descriptions"] = mapped
    if config.get("shared_description_config"):
        source_config = load_config(config["shared_description_config"])
        source = read(Path(source_config["output"]) / "descriptions.json")
        if (snapshot.get("shared_source_records_hash") != source.get("records_hash")
                or source.get("records_hash") != digest(source.get("records", []))):
            raise ValueError("공유 설명 원본이 변경되었습니다.")
        source_map = {r["post_key"]: r["description"] for r in source["records"]}
        if any(source_map.get(key) != record["description"] for key, record in mapped.items()):
            raise ValueError("공유 설명 부분집합이 원본과 다릅니다.")
    return snapshot


def shared_description_subset(data, source_data, source_records, source_logs):
    """Select identical immutable descriptions, checking media/author/caption/time.

    Log usage is attributed to the relevant size; it represents no new charge.
    """
    if data["people"] != source_data["people"] or data["app_relations"] != source_data["app_relations"]:
        raise ValueError("공유 설명의 가족 이름/관계가 다릅니다.")
    mapped = {r["post_key"]: r for r in source_records}
    logged = {r["post_key"]: r for r in source_logs}
    if len(mapped) != len(source_records) or len(logged) != len(source_logs):
        raise ValueError("공유 설명 중복")
    records, logs = [], []
    for item in history_records(data):
        key = item["id"]
        target, original = data["memory"][key], source_data["memory"].get(key)
        if (original is None or any(target[k] != original[k] for k in ("caption", "author_key", "created_at", "image_id"))
                or (target.get("image_path") and data["image_hashes"][target["image_id"]] != source_data["image_hashes"].get(original["image_id"]))):
            raise ValueError("공유 설명의 게시글/사진이 다릅니다.")
        if (key not in mapped or key not in logged or logged[key].get("status") != "complete"
                or logged[key].get("description") != mapped[key]["description"]):
            raise ValueError("공유 설명의 완료 로그가 없습니다.")
        records.append(mapped[key]); logs.append(logged[key])
    return records, logs


async def import_shared_descriptions(config, data, db, lock):
    """Paid-phase opt-in still required; copies a completed source without API calls."""
    from asgiref.sync import sync_to_async
    from django.db import transaction
    from apps.posts.models import Post
    source_config = load_config(config["shared_description_config"])
    if source_config.get("shared_description_config"):
        raise ValueError("공유 설명은 직접 생성한 단일 원본만 허용합니다.")
    source_data, source_lock = verify_prepared(source_config)
    if source_lock["common_protocol_hash"] != lock["common_protocol_hash"]:
        raise ValueError("공유 설명 원본의 앱/모델/프롬프트가 다릅니다.")
    source_output = Path(source_config["output"])
    source_db = read(source_output / "db_import.json")
    source_snapshot = description_snapshot(source_config, source_data, source_db, source_lock)
    source_logs = [json.loads(line) for line in (source_output / "descriptions.jsonl").read_text().splitlines()]
    records, logs = shared_description_subset(data, source_data, source_snapshot["records"], source_logs)
    output = Path(config["output"])
    if (output / "descriptions.jsonl").exists():
        raise ValueError("부분 복사 기록이 있습니다. 새 run을 사용하세요.")
    def store():
        with transaction.atomic():
            for record in records:
                post = Post.objects.get(pk=db["post_ids"][record["post_key"]], room_id=lock["family_id"])
                if post.description and post.description != record["description"]:
                    raise ValueError("기존 SQL 설명이 공유 원본과 다릅니다.")
                post.description = record["description"]; post.save(update_fields=["description"])
    await sync_to_async(store, thread_sensitive=True)()
    for row in logs:
        append(output / "descriptions.jsonl", {**row, "signature": lock["signature"],
            "shared_source_signature": source_lock["signature"], "reused_without_api_call": True,
            "usage_policy": "source record usage attributed to this size; not an additional API charge"})
    snapshot = {"status": "complete", "signature": lock["signature"], "records": records,
        "records_hash": digest(records), "db_ids_hash": digest(db["post_ids"]),
        "shared_source_records_hash": source_snapshot["records_hash"], "new_api_calls": 0}
    save(output / "descriptions.json", snapshot)
    return description_snapshot(config, data, db, lock)


async def describe(config):
    """Paid phase: use the app's actual image+caption description generator once.

    No graph writes. Completed posts may resume; an interrupted/failed charged
    attempt is never silently retried. Gold is never supplied to the generator.
    """
    from asgiref.sync import sync_to_async
    data, lock = verify_prepared(config)
    bootstrap(config, require_graph=False)
    db = await sync_to_async(seed_sql, thread_sensitive=True)(config, data, lock)
    output = Path(config["output"])
    if (output / "descriptions.json").exists():
        return description_snapshot(config, data, db, lock)
    if config.get("shared_description_config"):
        return await import_shared_descriptions(config, data, db, lock)
    from apps.posts.models import Post
    from integrations.ai.feed_description import describe_post
    path, progress = output / "descriptions.jsonl", output / "description_attempt.json"
    old = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    done = {r["post_key"]: r for r in old}
    if (len(done) != len(old) or not set(done) <= set(data["memory"])
            or any(r.get("signature") != lock["signature"] or r.get("status") != "complete" for r in old)):
        raise ValueError("실패/중복/다른 조건의 설명 로그가 있습니다. 새 run을 사용하세요.")
    if progress.exists() and read(progress).get("post_key") not in done:
        raise ValueError("완료를 확인할 수 없는 설명 호출이 있습니다. 자동 재호출하지 않습니다.")

    def fetch(key):
        return Post.objects.select_related("author").prefetch_related("photos").get(
            pk=db["post_ids"][key], room_id=lock["family_id"])

    records = []
    with instrument_sdk():
        for record in history_records(data):
            key = record["id"]
            if key in done:
                text = done[key]["description"]
                post = await sync_to_async(fetch, thread_sensitive=True)(key)
                if post.description != text:
                    raise ValueError("완료된 SQL 설명과 호출 로그가 다릅니다.")
            else:
                post = await sync_to_async(fetch, thread_sensitive=True)(key)
                if post.description:
                    raise ValueError("출처를 확인할 수 없는 기존 설명이 있습니다.")
                save(progress, {"signature": lock["signature"], "post_key": key, "status": "started"})
                started = time.perf_counter()
                with capture() as calls:
                    try:
                        text = await describe_post(post)
                        post.description = text
                        await sync_to_async(post.save, thread_sensitive=True)(update_fields=["description"])
                    except Exception as error:
                        append(path, {"signature": lock["signature"], "post_key": key, "status": "error",
                               "error_type": type(error).__name__, "calls": calls, "usage": totals(calls),
                               "seconds": time.perf_counter() - started})
                        raise
                append(path, {"signature": lock["signature"], "post_key": key, "status": "complete",
                       "description": text, "calls": calls, "usage": totals(calls),
                       "seconds": time.perf_counter() - started})
                print(f"사진·본문 설명: {key}", flush=True)
            records.append({"post_key": key, "description": text})
    snapshot = {"status": "complete", "signature": lock["signature"], "records": records,
                "records_hash": digest(records), "db_ids_hash": digest(db["post_ids"])}
    save(output / "descriptions.json", snapshot)
    return description_snapshot(config, data, db, lock)


async def seed(config):
    data, lock = verify_prepared(config)
    if not (Path(config["output"]) / "descriptions.json").exists():
        raise ValueError("describe 단계를 먼저 완료하세요. Graphiti 적재는 실행하지 않았습니다.")
    bootstrap(config)
    from asgiref.sync import sync_to_async
    db = await sync_to_async(seed_sql, thread_sensitive=True)(config, data, lock)
    descriptions = description_snapshot(config, data, db, lock)
    from integrations.ai_workers.graphiti_client import create_graphiti, close_graphiti
    from integrations.ai_workers.construction_graphiti import add_memory
    output = Path(config["output"])
    path = output / "graph_seed.json"
    group = f"family_{lock['family_id']}"
    graphiti = create_graphiti()
    wanted = expected_sources(data, db)
    try:
        existing = await graph_episodes(graphiti, group)
        if path.exists() and read(path).get("status") == "complete":
            report = read(path)
            if (report["signature"] != lock["signature"] or report.get("memory_snapshot_hash") != descriptions["records_hash"]
                    or existing != {k: v["text"] for k, v in wanted.items()}):
                raise ValueError("기존 그래프와 동결한 과거 기억이 다릅니다.")
            if await graph_fingerprint(graphiti, group) != report["fingerprint"]:
                raise ValueError("동결한 그래프가 변경되었습니다.")
            return report
        count, _, _ = await graphiti.driver.execute_query(
            "MATCH (n {group_id:$g}) RETURN count(n) AS count", g=group, routing_="r")
        if existing or path.exists() or count[0]["count"]:
            raise ValueError("이미 사용되었거나 부분 적재된 그룹입니다. 새 run_id/output으로 시작하세요. 기존 데이터는 삭제하지 않습니다.")
        save(path, {"status": "started", "signature": lock["signature"], "group_id": group})
        await graphiti.build_indices_and_constraints()
        with instrument_sdk():
            for record in history_records(data, data["descriptions"]):
                source = f"post_{db['post_ids'][record['id']]}"
                started = time.perf_counter()
                with capture() as calls:
                    try:
                        uid = await add_memory(graphiti, lock["family_id"], seed_body(record), source,
                                               datetime.fromisoformat(record["게시시각"]))
                    except Exception as error:
                        append(output / "ingestion.jsonl", {"post_key": record["id"], "status": "error",
                               "error_type": type(error).__name__, "calls": calls, "seconds": time.perf_counter() - started})
                        raise
                append(output / "ingestion.jsonl", {"post_key": record["id"], "episode_id": uid, "status": "complete",
                       "calls": calls, "usage": totals(calls), "seconds": time.perf_counter() - started})
                print(f"기억 적재: {record['id']}", flush=True)
        if await graph_episodes(graphiti, group) != {k: v["text"] for k, v in wanted.items()}:
            raise ValueError("적재된 과거 설명이 예상과 다릅니다.")
        report = {"status": "complete", "signature": lock["signature"], "group_id": group,
                  "memory_snapshot_hash": descriptions["records_hash"],
                  "memory_posts": len(data["memory"]), "probe_episodes": 0, "fingerprint": await graph_fingerprint(graphiti, group)}
        save(path, report)
        return report
    finally:
        await close_graphiti(graphiti)


def provided_sources(memories, wanted):
    """Only count a source if its complete text really reaches the final context."""
    keys = set()
    for memory in memories:
        for source in memory.get("sources", []):
            match = wanted.get(source.get("name"))
            if match is None or source.get("text") != match["text"]:
                raise ValueError("평가 글/다른 실험/변경된 source가 검색되었습니다.")
            keys.add(match["post_key"])
    return sorted(keys)


async def execute_task(task, config, data, lock, wanted):
    if file_hash(task["image_path"]) != task["image_sha256"]:
        raise ValueError("현재 사진이 준비 시점과 다릅니다.")
    from openai import AsyncOpenAI
    from integrations.ai import post_flow, prompts
    from integrations.ai_workers.graphiti_client import create_graphiti, close_graphiti
    from integrations.ai_workers.searching_graphiti import search_many
    graphiti = None
    searches, timings = [], {}
    payload = dict(task["payload"])
    if task["condition"] == "full_history":
        payload["가족기록"] = history_records(data, data["descriptions"])
    row = {**task, "signature": lock["signature"], "provided_post_ids": [], "searches": searches, "timings": timings}
    row["payload"] = payload
    row["memory_snapshot_hash"] = lock.get("memory_snapshot_hash")
    started = time.perf_counter()

    def observe_request(endpoint, options):
        if endpoint not in {"responses", "responses_parse"}:
            return
        if task["condition"] == "full_history":
            row["provided_post_ids"] = sorted(data["memory"])
            row["final_input_attempted"] = True
        elif task["condition"] == "graphiti" and options.get("tool_choice") == "none":
            contexts = [json.loads(item["output"]) for item in options["input"]
                        if isinstance(item, dict) and item.get("type") == "function_call_output"]
            combined = {"facts": [fact for context in contexts for fact in context["facts"]],
                        "sources": [source for context in contexts for source in context["sources"]]}
            row["provided_post_ids"] = provided_sources([{"sources": combined["sources"]}], wanted)
            row["final_memory_context"] = combined
            row["final_input_attempted"] = True

    async def search(queries):
        nonlocal graphiti
        if graphiti is None:
            graphiti = create_graphiti()
        results = await search_many(graphiti, lock["family_id"], queries, max_queries=config["max_queries"])
        provided_sources([m for r in results for m in r["memories"]], wanted)
        searches.append({"queries": queries, "raw_results": results})
        return results

    with capture(observe_request) as calls:
        try:
            if task["condition"] == "graphiti" or task["feature"] == "summary":
                feature = "post_summary" if task["feature"] == "summary" else "post_qa"
                result = await post_flow.answer(search, json.dumps(payload, ensure_ascii=False), feature,
                                               images=[Path(task["image_path"])], timings=timings)
                row["provided_post_ids"] = provided_sources(result["memories"], wanted)
                row["final_memory_context"] = post_flow.context(result["memories"])
            else:
                instructions = prompts.POST_SUMMARY if task["feature"] == "summary" else prompts.POST_QA
                content = [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)},
                           {"type": "input_image", "detail": config["image_detail"],
                            "image_url": "data:image/jpeg;base64," + base64.b64encode(Path(task["image_path"]).read_bytes()).decode()}]
                from django.conf import settings
                async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY,
                                       timeout=config["timeout_seconds"], max_retries=config["sdk_max_retries"]) as client:
                    response = await client.responses.create(model=config["model"], service_tier=config["service_tier"],
                        reasoning={"effort": config["reasoning_effort"]}, instructions=instructions, store=False,
                        input=[{"role": "user", "content": content}], max_output_tokens=config["answer_max_tokens"])
                result = {"text": post_flow.checked_text(response), "queries": [], "memories": []}
                timings["answer"] = time.perf_counter() - started
                if task["condition"] == "full_history":
                    row["provided_post_ids"] = sorted(data["memory"])
            row.update(status="complete", **result)
        except Exception as error:
            row.update(status="error", error_type=type(error).__name__, text="", queries=[], memories=[])
        finally:
            if graphiti is not None:
                await close_graphiti(graphiti)
    row.update(calls=calls, usage=totals(calls), total_seconds=time.perf_counter() - started)
    return row


async def run(config, phase):
    data, lock = verify_prepared(config)
    if not all((Path(config["output"]) / name).exists() for name in ("descriptions.json", "graph_seed.json", "db_import.json")):
        raise ValueError("describe와 seed 단계를 먼저 완료하세요. 평가 호출은 실행하지 않았습니다.")
    bootstrap(config)
    output = Path(config["output"])
    seed_report = read(output / "graph_seed.json")
    from asgiref.sync import sync_to_async
    db = await sync_to_async(seed_sql, thread_sensitive=True)(config, data, lock)
    descriptions = description_snapshot(config, data, db, lock)
    lock = {**lock, "memory_snapshot_hash": descriptions["records_hash"]}
    if (seed_report.get("status") != "complete" or seed_report.get("signature") != lock["signature"] or db.get("signature") != lock["signature"]
            or seed_report.get("memory_snapshot_hash") != descriptions["records_hash"]):
        raise ValueError("과거 기억 전체 적재 완료 상태가 필요합니다.")
    from integrations.ai_workers.graphiti_client import create_graphiti, close_graphiti
    checker = create_graphiti()
    path = output / f"results_{phase}.jsonl"
    planned = read(output / f"prepared/tasks_{phase}.json")
    old = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    done = {r["task_id"] for r in old}
    if (len(done) != len(old) or not done <= {t["task_id"] for t in planned}
            or any(r["signature"] != lock["signature"] or r.get("memory_snapshot_hash") != lock["memory_snapshot_hash"] for r in old)):
        raise ValueError("중복되거나 다른 실험의 결과가 있습니다.")
    wanted = expected_sources(data, db)
    try:
        before = await graph_fingerprint(checker, seed_report["group_id"])
        if before != seed_report["fingerprint"] or await graph_episodes(checker, seed_report["group_id"]) != {k: v["text"] for k, v in wanted.items()}:
            raise ValueError("동결한 그래프가 변경되었습니다. 실행을 중단합니다.")
        with instrument_sdk():
            for task in planned:
                if task["task_id"] in done:
                    continue
                row = await execute_task(task, config, data, lock, wanted)
                # Refuse a result affected by an external construction worker or another tester.
                if await graph_fingerprint(checker, seed_report["group_id"]) != before:
                    save(output / "graph_contamination.json", {"task_id": task["task_id"], "status": "invalid_run"})
                    raise ValueError("QA 도중 그래프가 변경되었습니다. 이 run은 사용하지 마세요.")
                append(path, row)
                print(f"{phase}: {task['task_id']} {row['status']}", flush=True)
        save(output / f"completion_{phase}.json", {"signature": lock["signature"], "task_count": len(planned),
             "graph_fingerprint": before, "warmup_excluded": False, "memory_snapshot_hash": lock["memory_snapshot_hash"]})
    finally:
        await close_graphiti(checker)
