import io
import secrets

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.api import APIError
from apps.families.models import Membership
from apps.families.services import relationship

from .models import Post

def current_room(request):
    membership = Membership.objects.select_related("room").filter(
        user=request.user
    ).order_by("joined_at", "pk").first()
    if membership is None:
        raise APIError("가족 방에 먼저 들어가 주세요.", 403)
    return membership.room


def post_for(request, pk):
    post = Post.objects.select_related("author", "room").filter(
        pk=pk, room=current_room(request)
    ).first()
    if post is None:
        raise APIError("게시물을 찾을 수 없어요.", 404)
    return post


def serialize(post, request):
    image_path = f"/api/posts/{post.pk}/image/"
    origin = settings.PUBLIC_ORIGIN
    return {
        "id": post.pk,
        "author_id": post.author_id,
        "author_name": post.author.display_name,
        "relationship": relationship(request.user, post.author, post.room),
        "created_at": timezone.localtime(post.created_at).isoformat(),
        "image_url": origin + image_path if origin else request.build_absolute_uri(image_path),
        "caption": post.caption,
        "comment_count": 0,
    }


def prepare_image(uploaded):
    if uploaded is None or uploaded.size > settings.MAX_UPLOAD_BYTES:
        raise APIError("사진을 다시 확인해 주세요. 사진은 10MB까지 올릴 수 있어요.")
    try:
        with Image.open(uploaded) as image:
            if image.width * image.height > settings.MAX_IMAGE_PIXELS:
                raise APIError("사진이 너무 커요. 다른 사진을 선택해 주세요.")
            image.verify()
        uploaded.seek(0)
        with Image.open(uploaded) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((settings.MAX_IMAGE_DIMENSION, settings.MAX_IMAGE_DIMENSION))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise APIError("읽을 수 없는 사진이에요. 다시 선택해 주세요.") from error
    return ContentFile(output.getvalue(), name=secrets.token_hex(12) + ".jpg")
