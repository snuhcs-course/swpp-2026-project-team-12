"""Map Graphiti sources back to dataset posts and the memory labels those posts establish."""
from __future__ import annotations


def establishes_map(manifest):
    return {event["feed_key"]: set(event.get("establishes", [])) for event in manifest["events"]}


def labels_for(feed_keys, establishes):
    return set().union(*(establishes.get(key, set()) for key in feed_keys)) if feed_keys else set()


def retrieved_feed_keys(memories, post_ids):
    """Graphiti names each episode post_<DB id>; keep the first-seen order of dataset posts."""
    by_source_name = {f"post_{post_id}": feed_key for feed_key, post_id in post_ids.items()}
    keys = []
    for memory in memories:
        for source in memory.get("sources", []):
            feed_key = by_source_name.get(source.get("name"))
            if feed_key and feed_key not in keys:
                keys.append(feed_key)
    return keys


def label_sources(manifest, labels):
    """Posts that establish any of the labels, as reference text for the judge."""
    labels = set(labels)
    return [
        {"feed_key": event["feed_key"], "author": event["author_name"],
         "created_at": event["created_at"], "caption": event["caption"]}
        for event in manifest["events"]
        if labels & set(event.get("establishes", []))
    ]
