"""Rule-based scores for each feature output. Values are bool, float, or None when a rule does not apply."""
from __future__ import annotations

import re

from ..common.labels import labels_for
from .cases import caption_numbers

SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
NEGATIONS = ("안 ", "못 ", "말고", "않", "없")
RELAY = ("전해", "말해줘", "말해 줘", "말해주", "말해 주")
LATIN_WORD = re.compile(r"[A-Za-z]{3,}")


def squash(text):
    return re.sub(r"\s+", "", text or "")


def unit_hits(text, units):
    """Each unit is a list of alternatives; a unit is found if any alternative appears, ignoring spaces."""
    body = squash(text)
    return [any(squash(option) in body for option in unit) for unit in units]


def ratio(values):
    return sum(values) / len(values) if values else None


def forbidden_found(text, strings):
    body = squash(text)
    return [value for value in strings if squash(value) and squash(value) in body]


def sentences(text):
    return [part for part in SENTENCE_END.split((text or "").strip()) if part.strip()]


def polite(sentence):
    """Formal or polite endings; trailing emoji and punctuation are ignored."""
    core = re.sub(r"[^가-힣]+$", "", sentence.strip())
    return core.endswith(("요", "니다", "죠"))


def polite_rate(text):
    return ratio([polite(sentence) for sentence in sentences(text)])


def coverage(text, case, units_key="must_include", forbidden_key="must_not_include"):
    found = unit_hits(text, case.get(units_key, []))
    return {
        "fact_recall": ratio(found),
        "missing_facts": [unit for unit, hit in zip(case.get(units_key, []), found) if not hit],
        "forbidden_strings": forbidden_found(text, case.get(forbidden_key, [])),
    }


def check_description(case, output):
    text = output["text"]
    count = len(sentences(text))
    return {
        **coverage(text, case),
        "sentence_count": count,
        "length_ok": 3 <= count <= 5,
    }


def check_summary(case, output):
    text = output["text"]
    return {
        **coverage(text, case),
        "relationship_mentioned": case["expected_relationship"] in text,
        "app_relationship_matches": output.get("relationship") == case["expected_relationship"]
        if output.get("relationship") else None,
        "polite_rate": polite_rate(text),
        # Informational only: the adapt prompt deliberately sets no sentence limit.
        "sentence_count": len(sentences(text)),
    }


def check_digest(case, output):
    paragraphs = {item["author_username"]: item["text"] for item in output["summaries"]}
    authors = {post["author_username"] for post in case["posts"]}
    text = "\n".join(paragraphs.values())
    sentence_counts = [len(sentences(paragraph)) for paragraph in paragraphs.values()]
    leaked = [caption for caption in case.get("other_day_captions", [])
              if len(squash(caption)) >= 8 and squash(caption) in squash(text)]
    return {
        **coverage(text, case),
        "every_author_once": set(paragraphs) == authors,
        "one_to_three_sentences": all(1 <= count <= 3 for count in sentence_counts),
        "other_day_caption_copied": leaked,
        "polite_rate": polite_rate(text),
    }


def answer_scores(text, case):
    units = case.get("answer_units", [])
    found = unit_hits(text, units)
    return {
        "answer_recall": ratio(found),
        "answer_correct": all(found) if units else None,
        "forbidden_strings": forbidden_found(text, case.get("forbidden_answer_strings", [])),
    }


def retrieval_scores(case, retrieved_keys, establishes):
    labels = labels_for(retrieved_keys, establishes)
    required = set(case.get("required_memories", []))
    relevant = required | set(case.get("optional_memories", []))
    forbidden = set(case.get("must_filter", []))
    recall = len(required & labels) / len(required) if required else None
    leaked = sorted(forbidden & labels)
    useful = [key for key in retrieved_keys if establishes.get(key, set()) & relevant]
    return {
        "retrieved_feed_keys": retrieved_keys,
        "required_recall": recall,
        "retrieval_source_precision": len(useful) / len(retrieved_keys) if retrieved_keys else None,
        # Retrieving the superseded record is expected for "what changed" questions; whether the
        # answer used it as current is the judge's no_stale_or_invented. Kept here as a diagnostic.
        "filter_leaked": leaked,
        "retrieval_pass": recall is None or recall == 1.0,
    }


def check_post_qa(case, output, retrieved_keys, establishes):
    searched = bool(output.get("query"))
    return {
        "search_decision_correct": searched == case["expects_search"],
        "searched": searched,
        "query_count": len(output.get("queries") or []),
        **answer_scores(output["text"], case),
        **(retrieval_scores(case, retrieved_keys, establishes) if searched else {}),
        "polite_rate": polite_rate(output["text"]),
    }


def answer_diversity(rows):
    """Distinct answers per post across viewers; 1.0 means every family member got a different answer."""
    answers = {}
    for row in rows:
        if "error" not in row:
            answers.setdefault(row["case"]["feed_key"], []).append(row["output"]["text"].strip())
    per_post = {key: len(set(texts)) / len(texts) for key, texts in answers.items()}
    return {"mean": sum(per_post.values()) / len(per_post), "by_post": per_post} if per_post else None


def check_stt(case, output):
    text = output["text"].strip()
    recognized = case["recognized"]
    kept_numbers = [value for value in caption_numbers(recognized) if value in text]
    negations = [word for word in NEGATIONS if word in recognized]
    return {
        "exact_match": squash(text).rstrip(".!") == squash(case.get("expected", "")).rstrip(".!")
        if case.get("expected") else None,
        "must_keep_recall": ratio(unit_hits(text, [[value] for value in case.get("must_keep", [])])),
        "must_remove_clean": not forbidden_found(text, case.get("must_remove", [])),
        "relay_removed": not any(word in text for word in RELAY),
        "numbers_kept": len(kept_numbers) == len(caption_numbers(recognized)),
        "negation_kept": all(word in text for word in negations) if negations else None,
        "single_line": "\n" not in text,
        "no_wrapper": not text.startswith(("\"", "'", "“", "댓글:", "출력:")),
        "stays_korean": not LATIN_WORD.search(text),
        "searched": bool(output.get("query")),
    }

