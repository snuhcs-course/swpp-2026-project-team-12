"""Build per-feature evaluation cases from a dataset manifest and an optional gold file.

Nothing here touches Django or the network, so case lists can be checked before any paid call.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

from ..common.labels import label_sources

# Family history (memory search) is evaluated by testbed/memoryqa_scaling, not here.
FEATURES = ("description", "summary", "digest", "post_qa", "stt")
NUMBER = re.compile(r"\d+(?:[.:/]\d+)*")


def caption_numbers(text):
    return list(dict.fromkeys(NUMBER.findall(text or "")))


def names_in(text, members):
    return [member["name"] for member in members if member["name"] in (text or "")]


def default_units(text, members):
    """Facts that any rewrite of the caption must keep: numbers and family names."""
    return [[value] for value in caption_numbers(text) + names_in(text, members)]


def events_by_key(manifest):
    return {event["feed_key"]: event for event in manifest["events"]}


def post_view(event):
    return {
        "feed_key": event["feed_key"],
        "author_username": event["author_username"],
        "author_name": event["author_name"],
        "created_at": event["created_at"],
        "caption": event["caption"],
        "image_paths": event.get("image_paths") or ([event["image_path"]] if event.get("image_path") else []),
    }


def description_cases(manifest, gold, post_ids):
    members = manifest["family"]["members"]
    cases = []
    for event in manifest["events"]:
        if event["feed_key"] not in post_ids:
            continue
        spec = gold.get("description", {}).get(event["feed_key"], {})
        cases.append({
            "id": event["feed_key"],
            **post_view(event),
            "must_include": spec.get("must_include", default_units(event["caption"], members)),
            "must_not_include": spec.get("must_not_include", []),
        })
    return cases


def summary_cases(manifest, gold, post_ids):
    members = manifest["family"]["members"]
    matrix = manifest["family"]["relationship_matrix"]
    cases = []
    for event in manifest["events"]:
        if event["feed_key"] not in post_ids:
            continue
        spec = gold.get("summary", {}).get(event["feed_key"], {})
        for viewer in members:
            if viewer["username"] == event["author_username"]:
                continue
            cases.append({
                "id": f"{event['feed_key']}@{viewer['username']}",
                **post_view(event),
                "viewer_username": viewer["username"],
                "viewer_name": viewer["name"],
                "expected_relationship": matrix[viewer["username"]][event["author_username"]],
                "must_include": spec.get("must_include", default_units(event["caption"], members)),
                "must_not_include": spec.get("must_not_include", []),
            })
    return cases


def event_day(event):
    return datetime.fromisoformat(event["created_at"]).date().isoformat()


def digest_cases(manifest, gold, post_ids):
    members = manifest["family"]["members"]
    days = defaultdict(list)
    for event in manifest["events"]:
        if event["feed_key"] in post_ids:
            days[event_day(event)].append(event)
    cases = []
    for day, events in sorted(days.items()):
        events.sort(key=lambda event: event["created_at"])
        spec = gold.get("digest", {}).get(day, {})
        other_days = [event["caption"] for event in manifest["events"]
                      if event["feed_key"] in post_ids and event_day(event) != day]
        cases.append({
            "id": day,
            "day": day,
            "posts": [post_view(event) for event in events],
            "must_include": spec.get("must_include", [
                unit for event in events for unit in default_units(event["caption"], members)
            ]),
            "must_not_include": spec.get("must_not_include", []),
            "other_day_captions": other_days,
        })
    return cases


def post_qa_cases(manifest, gold, post_ids):
    matrix = manifest["family"]["relationship_matrix"]
    cases = []
    for event in manifest["events"]:
        if event["kind"] != "probe" or event["feed_key"] not in post_ids:
            continue
        spec = gold.get("post_qa", {}).get(event["feed_key"], {})
        needed = event.get("required_memories", []) + event.get("optional_memories", [])
        for viewer in manifest["family"]["members"]:
            cases.append({
                "id": f"{event['feed_key']}@{viewer['username']}",
                **post_view(event),
                "viewer_username": viewer["username"],
                "viewer_name": viewer["name"],
                "expected_relationship": matrix[viewer["username"]][event["author_username"]],
                "question": event["evaluation_question"],
                "prior_dialogue": event.get("prior_dialogue", []),
                "expects_search": spec.get("expects_search", bool(needed)),
                "required_memories": event.get("required_memories", []),
                "optional_memories": event.get("optional_memories", []),
                "must_filter": event.get("must_filter", []),
                "answer_units": spec.get("answer_units", []),
                "forbidden_answer_strings": spec.get("forbidden_answer_strings", []),
                "reference": label_sources(manifest, needed),
                "stale_reference": label_sources(manifest, event.get("must_filter", [])),
            })
    return cases


def stt_cases(manifest, gold, post_ids):
    events = events_by_key(manifest)
    cases = []
    for reply in manifest.get("voice_replies", []):
        post = events[reply["feed_key"]]
        cases.append({
            **reply,
            "post_author_name": post["author_name"],
            "post_caption": post["caption"],
            "post_seeded": reply["feed_key"] in post_ids,
        })
    return cases


BUILDERS = {
    "description": description_cases,
    "summary": summary_cases,
    "digest": digest_cases,
    "post_qa": post_qa_cases,
    "stt": stt_cases,
}


def build_cases(feature, manifest, gold, post_ids):
    return BUILDERS[feature](manifest, gold or {}, post_ids)
