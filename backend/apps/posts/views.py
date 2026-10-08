from datetime import timedelta

from django.http import FileResponse
from django.db.models import Q
from django.utils import timezone

from apps.api import APIError, api
from apps.families.services import relationship
from integrations.ai import provider

from .models import AdaptedMessage, Post
from .services import current_room, post_for, prepare_image, serialize


@api("GET", "POST")
def feed(request):
    room = current_room(request)
    if request.method == "GET":
        posts = room.posts.select_related("author")[:100]
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
    return {**serialize(post, request), "comments": []}


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
    eligible = Q(status="pending") | Q(
        status="processing", updated_at__lt=timezone.now() - timedelta(minutes=2)
    )
    if request.method == "POST":
        eligible |= Q(status="failed")
    claimed = AdaptedMessage.objects.filter(pk=obj.pk).filter(eligible).update(
        status="processing", updated_at=timezone.now()
    )
    if claimed:
        try:
            obj.text = provider.adapt(post, relationship(request.user, post.author, post.room))
            obj.status = "ready"
        except provider.AIUnavailable:
            obj.status = "failed"
        obj.save()
    else:
        obj.refresh_from_db()
    return {"text": obj.text, "status": obj.status}
