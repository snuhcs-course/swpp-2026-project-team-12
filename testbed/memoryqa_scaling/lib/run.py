"""Fresh paid QA against restored snapshots; never reuse recorded answers/grades."""
import asyncio
import json
import os
from pathlib import Path

from .app import bootstrap
from .common import ROOT, dataset, digest, read, resolved_task, save, sha
from .graphs import canonical, check_graphs, connection, load_snapshot, read_group
from .read_only_database import read_only_database_scope
from .sql import check_sql
from .original.live import execute_task, expected_sources
from .original.usage import instrument_sdk


def run(size, output, *, allow_paid=False):
    if not allow_paid:
        raise ValueError("No paid call made. Fresh evaluation requires --allow-paid")
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("NEO4J_PASSWORD"):
        raise ValueError("Export OPENAI_API_KEY and NEO4J_PASSWORD")
    output=Path(output).resolve()
    if not (output/"sql_fixture.json").is_file():raise ValueError("Run restore-sql with this output directory first")
    config=bootstrap(size,output,require_key=True)
    check_sql(size,output)
    check_graphs()
    from .validate import check_inputs
    check_inputs(images=True)
    # check_sql opened a writable fixture connection before entering the original
    # read-only guard. Close it so any later SQL connection receives query_only.
    from django.db import connections
    connections.close_all()
    data=dataset(size)
    tasks=read(ROOT/f"panel/history_{size}/tasks.json")
    package_lock=read(ROOT/"bundle_manifest.json")
    lock={"signature":digest({"bundle":package_lock,"size":size}),
          "family_id":data["db"]["family_id"],
          "memory_snapshot_hash":read(ROOT/f"snapshots/history_{size}/descriptions.json")["records_hash"]}
    run_lock={"signature":lock["signature"],"history_size":size,"tasks":180,"model":config["model"],
              "app_commit":config["app_commit"],"description_generation_calls":0,"graph_extraction_calls":0,
              "grading":"Pending for these new answers; archived grades will not be reused"}
    path=output/"run_lock.json"
    if path.exists() and read(path)!=run_lock:raise ValueError("Output belongs to another execution contract")
    save(path,run_lock)
    result_path=output/"results.jsonl"
    done={}
    if result_path.exists():
        for line in result_path.read_text().splitlines():
            row=json.loads(line)
            if row["task_id"] in done or row.get("signature")!=lock["signature"]:raise ValueError("Output collision")
            if row["status"]!="complete":raise ValueError("An earlier service failure is preserved; create a separate run rather than silently replacing it")
            done[row["task_id"]]=row
    if not set(done)<={t["task_id"] for t in tasks}:raise ValueError("Output contains unknown tasks")
    wanted=expected_sources(data,data["db"])
    snapshot=load_snapshot(size)
    with connection() as driver:
        def unchanged():
            nodes,edges=read_group(driver,snapshot["group_id"])
            if digest(canonical(nodes,edges))!=snapshot["content_sha256"]:raise ValueError("Graph changed during QA; run invalid")
        async def execute():
            from .original.usage import totals
            with read_only_database_scope(),instrument_sdk():
                for task in tasks:
                    if task["task_id"] in done:continue
                    unchanged()
                    row=await execute_task(resolved_task(task),config,data,lock,wanted)
                    unchanged()
                    if row["status"]=="complete":
                        generations=[c for c in row["calls"] if c["endpoint"]!="embedding"]
                        if (not row["usage"]["usage_complete"] or any(
                                c.get("model")!=config["model"] or c.get("service_tier")!=config["service_tier"]
                                for c in generations)):
                            row.update(status="error",error_type="ProtocolDrift",
                                       protocol_error="Returned model/tier or complete usage differs from the fixed contract")
                    row["image_path"]=task["image_path"]
                    with result_path.open("a",encoding="utf-8") as stream:
                        stream.write(json.dumps(row,ensure_ascii=False)+"\n")
                    print(f"{size}: {len(done)+1}/180 {task['case_id']} {task['condition']} {row['status']}",flush=True)
                    done[row["task_id"]]=row
                    if row["status"]!="complete":raise RuntimeError("Service failure saved; execution stopped")
        asyncio.run(execute())
    save(output/"completion.json",{"tasks":len(done),"all_new_responses":True,"semantic_review":"pending",
        "instruction":"Review fresh answers and contexts against panel/qa_gold.json before reporting accuracy."})
    return {"history_size":size,"tasks":len(done),"semantic_review":"pending"}
