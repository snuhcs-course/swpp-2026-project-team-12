from datetime import timedelta

from django.http import FileResponse
from django.db.models import Count, Q
from django.utils import timezone

from apps.api import APIError, api, body, required
from apps.families.services import room_for
from apps.families.utils import relationship
from integrations.ai import provider

from .models import AdaptedMessage, Post
from .services import post_for, prepare_uploads, save_post, serialize


@api("POST")
def question(request, pk):
    post = post_for(request, pk)
    if post.kind == "question":
        raise APIError("오늘의 질문에서는 가족의 답변과 댓글을 확인해 주세요.")
    data = body(request)
    text = required(data, "question", 1000)
    dialogue = data.get("prior_dialogue", [])
    if not isinstance(dialogue, list) or len(dialogue) > 10:
        raise APIError("이전 대화는 최대 10개까지 보내 주세요.")
    clean = []
    for turn in dialogue:
        if not isinstance(turn, dict) or not isinstance(turn.get("role"), str) or turn["role"] not in {"user", "assistant"}:
            raise APIError("이전 대화 형식을 확인해 주세요.")
        clean.append({"role": turn["role"], "text": required(turn, "text", 1000)})
    try:
        return {"text": provider.ask(post, relationship(request.user, post.author, post.room),
                                     text, clean, request.user.display_name)}
    except provider.AIUnavailable as error:
        raise APIError("답변을 준비하지 못했어요. 잠시 후 다시 시도해 주세요.", 503) from error


@api("GET", "POST")
def feed(request):
    room = room_for(request)
    if request.method == "GET":
        posts = (room.posts.filter(kind="news").select_related("author")
                 .annotate(comment_count=Count("comments")).order_by("-created_at", "-id")[:100])
        from .daily_questions import ensure_today, status
        return {"posts": [serialize(post, request) for post in posts],
                "daily_question": status(ensure_today(room), request.user)}

    caption = request.POST.get("caption", "").strip()
    if len(caption) > 2000:
        raise APIError("글은 2000자까지 올릴 수 있어요.")
    images = prepare_uploads(request)
    post = save_post(room=room, author=request.user, caption=caption, images=images)
    return serialize(post, request)


@api("GET")
def detail(request, pk):
    post = post_for(request, pk)
    return {
        **serialize(post, request),
        "comments": [
            {
                "id": comment.pk,
                "author_name": comment.author.display_name,
                "relationship": relationship(request.user, comment.author, post.room),
                "text": comment.text,
                "source": comment.source,
                "created_at": timezone.localtime(comment.created_at).isoformat(),
            }
            for comment in post.comments.select_related("author")
        ],
    }


@api("GET")
def photo(request, pk, image_index=0):
    post = post_for(request, pk)
    if not 0 <= image_index < len(post.images):
        raise APIError("사진을 찾을 수 없어요.", 404)
    response = FileResponse(post.photo_files()[image_index].open("rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=300"
    return response


@api("GET", "POST")
def message(request, pk):
    post = post_for(request, pk)
    if post.kind == "question":
        raise APIError("오늘의 질문에서는 가족의 답변과 댓글을 확인해 주세요.")
    obj, _ = AdaptedMessage.objects.get_or_create(post=post, viewer=request.user)
    version = provider.summary_cache_version()
    eligible = Q(status="pending") | Q(
        status="processing", updated_at__lt=timezone.now() - timedelta(minutes=2)
    )
    eligible |= Q(status="ready") & ~Q(prompt_version=version)
    if request.method == "POST":
        eligible |= Q(status="failed")
    claimed_at = timezone.now()
    claimed = AdaptedMessage.objects.filter(pk=obj.pk).filter(eligible).update(
        status="processing", updated_at=claimed_at, prompt_version=version, text=""
    )
    if claimed:
        try:
            text = provider.adapt(post, relationship(request.user, post.author, post.room))
            status = "ready"
        except provider.AIUnavailable:
            text, status = "", "failed"
        # Preserve both cache-version claims and invalidation after profile changes.
        AdaptedMessage.objects.filter(
            pk=obj.pk, status="processing", updated_at=claimed_at, prompt_version=version
        ).update(
            text=text, status=status, updated_at=timezone.now()
        )
    obj.refresh_from_db()
    return {"text": obj.text, "status": obj.status}
