"""Call each feature the way the app does. Import only after TalkDockDjangoAdapter.setup() has configured Django."""
from __future__ import annotations

import json


def load_posts(post_ids):
    from apps.posts.models import Post

    posts = Post.objects.select_related("author", "room").in_bulk(list(post_ids.values()))
    return {key: posts[pk] for key, pk in post_ids.items() if pk in posts}


def run_description(case, posts, regenerate=False, **_):
    """Construction already stores descriptions; reuse them unless asked to regenerate."""
    from asgiref.sync import async_to_sync
    from integrations.ai.feed_description import describe_post

    post = posts[case["feed_key"]]
    if post.description and not regenerate:
        return {"text": post.description, "source": "stored"}
    return {"text": async_to_sync(describe_post)(post), "source": "generated"}


def run_summary(case, posts, **_):
    from apps.accounts.models import User
    from apps.families.utils.relationships import relationship
    from integrations.ai import provider

    post = posts[case["feed_key"]]
    viewer = User.objects.get(username=case["viewer_username"])
    # The app computes the relation from the family tree; keep it to compare with the manifest.
    relation = relationship(viewer, post.author, post.room)
    return {"text": provider.adapt(post, relation), "relationship": relation}


def run_digest(case, posts, **_):
    from integrations.ai import provider

    day_posts = sorted((posts[post["feed_key"]] for post in case["posts"]), key=lambda post: (post.created_at, post.pk))
    authors = {post.author_id: post.author for post in day_posts}
    return {"summaries": [{
        "author_username": authors[item["author_id"]].username,
        "author_name": authors[item["author_id"]].display_name,
        "text": item["text"],
    } for item in provider.summarize(day_posts)]}


def run_stt(case, posts, family_id, **_):
    from apps.accounts.models import User
    from apps.families.utils.tree import family_names
    from integrations.ai.provider import rewrite_payload
    from integrations.ai_workers.searching_workers import run_search

    # Same payload as apps.replies.views.prepare → provider.rewrite, called directly to keep the search decision.
    post = posts[case["feed_key"]]
    speaker = User.objects.get(username=case["speaker_username"]).display_name if case.get("speaker_username") else None
    payload = rewrite_payload(case["recognized"], post.author.display_name, speaker=speaker,
                              caption=post.caption, family_names=family_names(post.room))
    result = run_search("stt_correction", family_id, payload)
    return {"text": result["text"][:4000], "query": result.get("query"),
            "queries": result.get("queries", []), "memories": result.get("memories", [])}


def build_post_qa_input(post, case, relation, current_time):
    """Mirror integrations.ai.provider.ask without hiding retrieval metadata."""
    return json.dumps({
        "작성자": post.author.display_name,
        "관계": relation,
        "원문": post.caption,
        "게시시각": post.created_at.isoformat(),
        "질문": case["question"],
        "질문자": case["viewer_name"],
        "이전대화": case.get("prior_dialogue", []),
        "현재시각": current_time.isoformat(),
    }, ensure_ascii=False)


def run_post_qa(case, posts, family_id, **_):
    from django.utils import timezone
    from integrations.ai_workers.searching_workers import run_search

    post = posts[case["feed_key"]]
    content = build_post_qa_input(post, case, case["expected_relationship"], timezone.now())
    result = run_search("post_qa", family_id, content, images=post.photo_files())
    return {"text": result["text"], "query": result.get("query"), "queries": result.get("queries", []),
            "memories": result.get("memories", [])}


RUNNERS = {
    "description": run_description,
    "summary": run_summary,
    "digest": run_digest,
    "post_qa": run_post_qa,
    "stt": run_stt,
}
