from apps.api import api, body, required
from apps.posts.services import post_for

from .models import Comment


@api("POST")
def text_comment(request, pk):
    post = post_for(request, pk)
    text = required(body(request), "text", 2000)
    comment = Comment.objects.create(post=post, author=request.user, text=text)
    return {"id": comment.pk}
