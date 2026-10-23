"""Offline dataset, evidence, image and result verification."""
from __future__ import annotations

import hashlib
import math
from datetime import datetime
from statistics import mean

from .common import ROOT, SIZES, dataset, digest, manifest, read, relative_path, sha
from .download import image_destination, valid_file
from .original.app_contract import relationships
from .original.protocol import history_records
from .original.usage import totals

UPDATE = {"FQ04","FQ05","FQ06","FQ07","FQ08","FQ09","FQ10","FQ11","FQ13","FQ15","FQ17"}


def check_inputs(*, images=False, directory=None):
    source=manifest();ids={a["image_id"]:a for a in source["images"]}
    qa=read(ROOT/"panel/qa_runtime.json");gold={g["question_id"]:g for g in read(ROOT/"panel/qa_gold.json")}
    if len(qa)!=30 or len(gold)!=30 or {q["question_id"] for q in qa}!=set(gold):raise ValueError("Expected 30 matching questions and Gold labels")
    prior={};levels={};plans=set()
    for size in SIZES:
        data=dataset(size);memory=data["memory"];probes=data["probes"]
        base=ROOT/f"datasets/history_{size}"
        for name,expected in read(base/"checksums.json").items():
            if sha(base/name)!=expected:raise ValueError("Relocated dataset checksum differs: "+name)
        if len(memory)!=size or len(probes)!=20 or set(memory)&set(probes):raise ValueError("Post counts or IDs differ")
        if not set(prior)<set(memory) and size!=100:raise ValueError("Histories are not nested")
        if any(memory[k]!=v for k,v in prior.items()):raise ValueError("Common history changed")
        photos={p["image_id"] for p in memory.values() if p.get("image_path")}
        if len(photos)!=size*2//5 or not photos<=ids.keys():raise ValueError("Historical photo counts differ")
        for post in list(memory.values())+list(probes.values()):
            if post.get("image_path")!=None:
                relative_path(post["image_path"])
                if post["image_path"]!=ids[post["image_id"]]["path"]:raise ValueError("Image path is not the manifest path")
        for probe in probes.values():
            old=memory[probe["reshared_from_post_key"]]
            if old["image_id"]!=probe["image_id"] or datetime.fromisoformat(old["created_at"])>=datetime.fromisoformat(probe["created_at"]):raise ValueError("Reshare mismatch")
        if set(data["descriptions"])!=set(memory):raise ValueError("Frozen descriptions missing")
        if set(data["db"]["post_ids"])!=set(memory)|set(probes):raise ValueError("SQL source IDs missing")
        from .graphs import load_snapshot
        graph=load_snapshot(size)
        actual_episodes={n["p"]["name"]:n["p"]["content"] for n in graph["nodes"] if "Episodic" in n["labels"]}
        expected_episodes={f"post_{data['db']['post_ids'][k]}":f"작성자: {data['people'][p['author_key']]}\n상세 설명: {data['descriptions'][k]['description']}"
                           for k,p in memory.items()}
        if actual_episodes!=expected_episodes:raise ValueError("Graph episodes differ from the frozen history or include current posts")
        if any(n["p"].get("group_id")!=graph["group_id"] for n in graph["nodes"]):raise ValueError("Graph group leakage")
        for q in qa:
            if q["current_post_key"] not in probes:raise ValueError("Question references unknown current post")
            asked=datetime.fromisoformat(q["asked_at"])
            if any(datetime.fromisoformat(p["created_at"])>=asked for p in memory.values()):raise ValueError("Future history leakage")
            for group in gold[q["question_id"]]["sufficient_evidence_sets"]:
                if not group or not set(group)<=set(memory):raise ValueError("Gold source missing at a history size")
        tasks=read(ROOT/f"panel/history_{size}/tasks.json")
        if len(tasks)!=180:raise ValueError("Expected 180 tasks per size")
        by_id={q["question_id"]:q for q in qa}
        expected={(qid,c,r) for qid in gold for c in ("full_history","graphiti") for r in (1,2,3)}
        if {(t["case_id"],t["condition"],t["repeat"]) for t in tasks}!=expected:raise ValueError("Task panel is incomplete or duplicated")
        for task in tasks:
            q=by_id[task["case_id"]];probe=probes[q["current_post_key"]]
            if task["image_path"]!=probe["image_path"] or task["image_sha256"]!=ids[probe["image_id"]]["sha256"]:raise ValueError("Task current photo differs")
            payload=task["payload"]
            if payload["질문"]!=q["question"] or payload["원문"]!=probe["caption"] or payload["이전대화"]!=[]:raise ValueError("Question payload differs")
            if any(k in payload for k in ("expected_answer","sufficient_evidence_sets","required_answer_units")):raise ValueError("Gold leakage")
            if task["task_id"] in plans:raise ValueError("Duplicate task ID")
            plans.add(task["task_id"])
        levels[str(size)]={"posts":size,"photos":len(photos),"current_posts":20,"questions":30,"tasks":180,
                           "evidence_ids_valid":True,"graph_episodes_verified":len(actual_episodes)}
        prior=memory
    checked=0
    if images:
        from PIL import Image
        for row in source["images"]:
            path=image_destination(row,directory)
            if not valid_file(path,row):raise ValueError(f"Image missing or different: {row['image_id']}")
            with Image.open(path) as picture:picture.verify()
            checked+=1
    return {"levels":levels,"tasks":len(plans),"image_hashes_verified":checked,"paid_calls":0,"database_access":False}


def recorded_rows():
    import json
    return [json.loads(line) for n in SIZES for line in (ROOT/f"results/history_{n}/results.jsonl").read_text().splitlines()]


def summarize(rows, grades):
    usage=totals([c for r in rows for c in r["calls"]])
    count=len(rows);times=sorted(r["total_seconds"] for r in rows)
    get=lambda r:grades[r["task_id"]]
    strict=sum(get(r)["answer_satisfied"] and not get(r)["additional_false_claim"] for r in rows)
    updates=[r for r in rows if r["case_id"] in UPDATE]
    return {"tasks":count,"answer_satisfied":sum(get(r)["answer_satisfied"] for r in rows),
        "answer_satisfaction_rate":mean(get(r)["answer_satisfied"] for r in rows),"strict_correct":strict,"answer_accuracy":strict/count,
        "evidence_sufficient":sum(get(r)["evidence_sufficient"] for r in rows),"evidence_coverage":mean(get(r)["evidence_sufficient"] for r in rows),
        "source_coverage":sum(get(r)["source_coverage"] for r in rows),
        "false_connections":sum(get(r)["false_connection"] for r in rows),
        "unsupported_additions":sum(get(r)["additional_false_claim"] for r in rows),
        "memory_update_errors":sum(get(r)["memory_update_error"] for r in updates),"memory_update_subset_tasks":len(updates),
        "generation_tokens_per_question":usage["observed_generation_tokens"]/count,
        "embedding_tokens_per_question":usage["observed_embedding_tokens"]/count,
        "mean_seconds":mean(times),"p95_seconds":times[math.ceil(.95*count)-1],"errors":sum(r["status"]!="complete" for r in rows)}


def verify_results():
    import json
    rows=recorded_rows();grades={r["task_id"]:r["grade"] for r in read(ROOT/"results/grade_index.json")}
    if len(rows)!=540 or len({r["task_id"] for r in rows})!=540 or len(grades)!=540:raise ValueError("Recorded result count differs")
    report=read(ROOT/"results/comparison.json");output={};responses=[]
    for size in SIZES:
        data=dataset(size);plans={t["task_id"]:t for t in read(ROOT/f"panel/history_{size}/tasks.json")}
        sources=history_records(data,data["descriptions"])
        subset=[r for r in rows if r["history_size"]==size]
        if {r["task_id"] for r in subset}!=set(plans):raise ValueError("Recorded tasks differ from the frozen plan")
        wanted={f"post_{data['db']['post_ids'][r['id']]}":r for r in sources}
        for row in subset:
            task=plans[row["task_id"]]
            for field in ("case_id","condition","repeat","current_post_key","viewer_key","image_path","image_sha256","as_of"):
                if row[field]!=task[field]:raise ValueError("Recorded task drift: "+field)
            expected=dict(task["payload"])
            if row["condition"]=="full_history":expected["가족기록"]=sources
            if row["payload"]!=expected:raise ValueError("Recorded model payload differs")
            grade=grades[row["task_id"]]
            if hashlib.sha256(row["text"].encode()).hexdigest()!=grade["answer_sha256"]:raise ValueError("Answer/grade hash mismatch")
            if row["condition"]=="graphiti":
                if digest(row.get("final_memory_context",{}))!=grade["context_sha256"]:raise ValueError("Context/grade hash mismatch")
                for source in row.get("final_memory_context",{}).get("sources",[]):
                    original=wanted[source["name"]]
                    expected_text=f"작성자: {original['작성자']}\n상세 설명: {original['상세 설명']}"
                    if source["text"]!=expected_text:raise ValueError("Retrieved source differs from frozen descriptions")
            for call in row["calls"]:
                if call.get("response_id"):responses.append(call["response_id"])
                if call["endpoint"]!="embedding" and (call.get("model")!="gpt-6-luna" or call.get("service_tier")!="fast" or call.get("requested_reasoning")!={"effort":"none"}):raise ValueError("Recorded model configuration differs")
        output[str(size)]={}
        for condition in ("full_history","graphiti"):
            metrics=summarize([r for r in subset if r["condition"]==condition],grades)
            expected=report["levels"][str(size)][condition]
            for key,value in metrics.items():
                if not math.isclose(value,expected[key],rel_tol=1e-12,abs_tol=1e-12):raise ValueError(f"Recomputed metric differs: {size}/{condition}/{key}")
            output[str(size)][condition]=metrics
    if len(responses)!=len(set(responses)):raise ValueError("Recorded response IDs reused")
    return {"tasks":540,"all_six_cells_recomputed":True,"grades":"Saved AI semantic grades; independent human review pending",
            "metrics":output,"paid_calls":0,"database_access":False}
