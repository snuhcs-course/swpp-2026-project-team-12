"""Feature prompts and synchronous adapters to the shared memory flow."""

import json
import hashlib

from django.conf import settings
from django.utils import timezone
from . import prompts


class AIUnavailable(Exception):
    pass


def summary_cache_version():
    value = (prompts.POST_SUMMARY, settings.SUMMARY_AI_MODEL, settings.SUMMARY_AI_SERVICE_TIER,
             settings.SUMMARY_AI_REASONING_EFFORT, "high", prompts.ANSWER_MAX_TOKENS, "ordered-post-images-v1")
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


FEATURE_INSTRUCTIONS = {
    "post_summary": prompts.POST_SUMMARY,
    "post_qa": prompts.POST_QA,
    "stt_correction": prompts.STT_CORRECTION,
    "digest": prompts.DIGEST,
}


def answer_with_memory(feature, family_id, text, images=()):
    """Return author paragraphs for digest, display text for the other features."""
    from integrations.ai_workers.searching_workers import SearchUnavailable, run_search

    if not settings.OPENAI_API_KEY:
        raise AIUnavailable("AI 서비스를 설정하지 않았어요.")
    try:
        result = run_search(feature, family_id, text, images=images)
        return result["summaries"] if feature == "digest" else result["text"][:4000]
    except SearchUnavailable as error:
        raise AIUnavailable("AI 요청을 처리하지 못했어요.") from error


def adapt(post, relation):
    return answer_with_memory(
        "post_summary", post.room_id,
        json.dumps({"작성자": post.author.display_name, "관계": relation, "원문": post.caption, "게시시각": post.created_at.isoformat()}, ensure_ascii=False),
        post.photo_files(),
    )


def rewrite_payload(recognized, name, *, speaker=None, caption=None, family_names=()):
    """STT input; names let the model fix misheard family names without a search."""
    payload = {"게시물 작성자": name}
    if speaker:
        payload["말하는 사람"] = speaker
    if caption:
        payload["게시물 원문"] = caption
    if family_names:
        payload["가족 이름 목록"] = list(family_names)
    payload["인식된 말"] = recognized
    return json.dumps(payload, ensure_ascii=False)


def rewrite(recognized, name, *, family_id, speaker=None, caption=None, family_names=()):
    return answer_with_memory(
        "stt_correction", family_id,
        rewrite_payload(recognized, name, speaker=speaker, caption=caption, family_names=family_names),
    )


def summarize(posts):
    if not posts or any(post.room_id != posts[0].room_id for post in posts):
        raise AIUnavailable("같은 가족의 게시물로 요약을 요청하세요.")
    authors, images = {}, []
    for index, post in enumerate(posts):
        photos = post.photo_files()
        # Preserve the existing eight-post/eight-image budget and source order.
        selected = photos[:max(0, 8 - len(images))] if index < 8 else []
        photo_numbers = list(range(len(images) + 1, len(images) + len(selected) + 1))
        images.extend(selected)
        author = authors.setdefault(post.author_id, {
            "작성자 ID": post.author_id, "작성자": post.author.display_name, "게시글": [],
        })
        author["게시글"].append({
            "게시글 ID": post.pk, "게시시각": post.created_at.isoformat(), "원문": post.caption,
            "첨부 사진 수": len(photos), "전달 사진 번호": photo_numbers,
        })
    return answer_with_memory(
        "digest", posts[0].room_id,
        json.dumps(list(authors.values()), ensure_ascii=False), images,
    )


def ask(post, relation, question, prior_dialogue, viewer_name):
    return answer_with_memory(
        "post_qa", post.room_id,
        json.dumps({"작성자": post.author.display_name, "관계": relation, "원문": post.caption,
                    "게시시각": post.created_at.isoformat(), "질문": question,
                    "질문자": viewer_name, "이전대화": prior_dialogue, "현재시각": timezone.now().isoformat()}, ensure_ascii=False),
        post.photo_files(),
    )
