"""Describe a caption and all ordered post photos before graph construction."""

import base64
import io
import json

from asgiref.sync import sync_to_async
from django.conf import settings
from openai import AsyncOpenAI
from PIL import Image, ImageOps

from . import prompts
from .options import model_options


def construction_jpeg(data):
    """Return JPEG bytes within the construction byte and dimension limits, downsampling only when needed."""
    max_bytes, max_side = settings.CONSTRUCTION_IMAGE_MAX_BYTES, settings.CONSTRUCTION_IMAGE_MAX_DIMENSION
    with Image.open(io.BytesIO(data)) as source:
        if len(data) <= max_bytes and max(source.size) <= max_side and source.format == "JPEG":
            return data
        image = ImageOps.exif_transpose(source).convert("RGB")
    image.thumbnail((max_side, max_side))

    def encode(picture, quality):
        output = io.BytesIO()
        picture.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()

    # Lower quality first, then shrink further; a 256px floor keeps the photo legible to the model.
    for quality in (85, 75, 65):
        encoded = encode(image, quality)
        if len(encoded) <= max_bytes:
            return encoded
    while max(image.size) > 256:
        image = image.resize((max(1, int(image.width * .8)), max(1, int(image.height * .8))), Image.LANCZOS)
        encoded = encode(image, 65)
        if len(encoded) <= max_bytes:
            return encoded
    return encoded


def _description_content(post):
    """Read lazy ORM relations and media outside the async event loop."""
    content = [{"type": "input_text", "text": json.dumps({
        "작성자": post.author.display_name,
        "작성 시각": post.created_at.isoformat(),
        "원문": post.caption,
    }, ensure_ascii=False)}]
    for photo in post.photo_files():
        with photo.open("rb") as image:
            content.append({
                "type": "input_image", "detail": "high",
                "image_url": "data:image/jpeg;base64," + base64.b64encode(construction_jpeg(image.read())).decode(),
            })
    return content


async def describe_post(post):
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("게시물 설명을 생성하려면 OPENAI_API_KEY를 설정하세요.")
    content = await sync_to_async(_description_content, thread_sensitive=True)(post)
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=1) as client:
        response = await client.responses.create(
            **model_options("SUMMARY"), instructions=prompts.POST_DESCRIPTION,
            input=[{"role": "user", "content": content}],
            max_output_tokens=2000, store=False,
        )
    if response.status != "completed" or not response.output_text.strip():
        raise RuntimeError("게시물 상세 설명이 완료되지 않았습니다.")
    return response.output_text.strip()
