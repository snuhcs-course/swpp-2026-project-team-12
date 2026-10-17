from datetime import timedelta

from django.http import FileResponse
from django.db.models import Count, Q
from django.utils import timezone

from apps.api import APIError, api, body, required
from apps.families.services import relationship
from integrations.ai import provider

from .models import AdaptedMessage, Post
from .services import current_room, post_for, prepare_image, serialize


@api("POST")
def question(request, pk):
    post = post_for(request, pk)
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
    room = current_room(request)
    if request.method == "GET":
        posts = room.posts.select_related("author").annotate(comment_count=Count("comments"))[:100]
        return {"posts": [serialize(post, request) for post in posts]}

    caption = request.POST.get("caption", "").strip()
    if len(caption) > 2000:
        raise APIError("글은 2000자까지 올릴 수 있어요.")
    image = prepare_image(request.FILES.get("image"))
    post = Post.objects.create(room=room, author=request.user, caption=caption, image=image)
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
def photo(request, pk):
    post = post_for(request, pk)
    response = FileResponse(post.image.open("rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=300"
    return response


@api("GET", "POST")
def message(request, pk):
    post = post_for(request, pk)
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
            obj.text = provider.adapt(post, relationship(request.user, post.author, post.room))
            obj.status = "ready"
        except provider.AIUnavailable:
            obj.status = "failed"
        # A timed-out older request must not overwrite a newer claim.
        AdaptedMessage.objects.filter(pk=obj.pk, updated_at=claimed_at, prompt_version=version).update(
            text=obj.text if obj.status == "ready" else "", status=obj.status, updated_at=timezone.now()
        )
    obj.refresh_from_db()
    return {"text": obj.text, "status": obj.status}
