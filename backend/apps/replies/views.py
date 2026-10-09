from django.db import transaction

from apps.api import APIError, api, body, required
from apps.posts.services import post_for
from integrations.ai import provider

from .models import Comment, VoiceDraft


@api("POST")
def text_comment(request, pk):
    post = post_for(request, pk)
    text = required(body(request), "text", 2000)
    comment = Comment.objects.create(post=post, author=request.user, text=text)
    return {"id": comment.pk}


@api("POST")
def prepare(request, pk):
    post = post_for(request, pk)
    recognized = required(body(request), "recognized", 2000)
    try:
        converted = provider.rewrite(recognized, post.author.display_name)
    except provider.AIUnavailable as error:
        raise APIError("댓글을 정리하지 못했어요. 다시 시도해 주세요.", 503) from error
    draft = VoiceDraft.objects.create(
        post=post, author=request.user, recognized=recognized, converted=converted
    )
    return {
        "id": draft.pk,
        "recognized": draft.recognized,
        "converted": draft.converted,
        "post_id": post.pk,
        "author_name": post.author.display_name,
    }


@api("POST")
def send(request, pk):
    with transaction.atomic():
        draft = VoiceDraft.objects.select_related("post").filter(pk=pk, author=request.user).first()
        if draft is None:
            raise APIError("답장을 찾을 수 없어요.", 404)
        post_for(request, draft.post_id)
        comment, _ = Comment.objects.get_or_create(
            draft=draft,
            defaults={
                "post": draft.post,
                "author": request.user,
                "text": draft.converted,
                "source": "voice",
            },
        )
    return {"id": comment.pk, "post_id": comment.post_id}
