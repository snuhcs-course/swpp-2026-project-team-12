"""Describe a caption and all ordered post photos before graph construction."""

import base64
import json

from asgiref.sync import sync_to_async
from django.conf import settings
from openai import AsyncOpenAI

from . import prompts
from .options import model_options


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
                "image_url": "data:image/jpeg;base64," + base64.b64encode(image.read()).decode(),
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
