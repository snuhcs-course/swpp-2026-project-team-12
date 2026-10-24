import io
import secrets
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.api import APIError
from apps.families.models import Membership
from apps.families.utils import relationship

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
    comment_count = getattr(post, "comment_count", None)
    if comment_count is None:
        comment_count = post.comments.count()
    def url(path):
        return origin + path if origin else request.build_absolute_uri(path)
    images = [{"id": index, "url": url(f"/api/posts/{post.pk}/images/{index}/")}
              for index in range(len(post.images))]
    return {
        "id": post.pk,
        "author_id": post.author_id,
        "author_name": post.author.display_name,
        "relationship": relationship(request.user, post.author, post.room),
        "created_at": timezone.localtime(post.created_at).isoformat(),
        "image_url": url(image_path) if images else "",
        "images": images,
        "image_count": len(images),
        "caption": post.caption,
        "comment_count": comment_count,
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


def prepare_uploads(request):
    singles, multiples = request.FILES.getlist("image"), request.FILES.getlist("images")
    if singles and multiples:
        raise APIError("사진은 image 또는 images 중 한 방식으로 보내 주세요.")
    uploads = multiples or singles
    if len(uploads) > settings.MAX_POST_IMAGES:
        raise APIError("사진은 한 번에 5장까지 올릴 수 있어요.")
    if sum(photo.size for photo in uploads) > settings.MAX_POST_UPLOAD_BYTES:
        raise APIError("사진의 전체 크기는 30MB까지 올릴 수 있어요.")
    return [prepare_image(photo) for photo in uploads]


def save_post(room, author, caption, images):
    """Validate all files first; roll back DB and clean stored files on failure."""
    if not images and not caption.strip():
        raise APIError("글이나 사진을 하나 이상 남겨 주세요.")
    created_files = []
    try:
        with transaction.atomic():
            paths = []
            for image in images:
                name = default_storage.save(timezone.localtime().strftime("posts/%Y/%m/") + image.name, image)
                created_files.append((default_storage, name))
                paths.append(name)
            post = Post.objects.create(room=room, author=author, caption=caption, images=paths)
        return post
    except Exception:
        for storage, name in created_files:
            try:
                storage.delete(name)
            except Exception:
                logging.getLogger(__name__).exception("Could not clean up failed post upload")
        raise
