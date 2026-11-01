"""Resolve retrieved episode provenance to current, room-scoped feed posts."""

import re

from django.db.models import Count

from apps.posts.models import Post
from apps.posts.services import serialize


def evidence_posts(result, room, request):
    # New answers explicitly cite episodes; older workers only expose retrievals.
    cited = result.get("source_episode_ids")
    selected = set(cited) if isinstance(cited, list) else None
    ids = []
    for memory in result.get("memories", []):
        for source in memory.get("sources", []):
            if selected is not None and source.get("id") not in selected:
                continue
            match = re.fullmatch(r"post_([1-9][0-9]{0,17})", source.get("name", ""))
            if match and int(match[1]) not in ids:
                ids.append(int(match[1]))
    # Preserve the answer's citation order, rather than database/creation order.
    if selected is not None:
        names = {source["id"]: source.get("name", "")
                 for memory in result.get("memories", []) for source in memory.get("sources", [])}
        ordered = []
        for episode in cited:
            match = re.fullmatch(r"post_([1-9][0-9]{0,17})", names.get(episode, ""))
            if match and int(match[1]) not in ordered:
                ordered.append(int(match[1]))
        ids = ordered
    posts = {post.pk: post for post in Post.objects.filter(room=room, kind="news", pk__in=ids)
             .select_related("author", "room").annotate(comment_count=Count("comments"))}
    return {"evidence_posts": [serialize(posts[pk], request) for pk in ids if pk in posts],
            "evidence_kind": "cited" if selected is not None else "retrieved"}
