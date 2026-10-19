"""Describe a caption and all ordered post photos before graph construction."""

import base64
import json

from asgiref.sync import sync_to_async
from django.conf import settings
from openai import AsyncOpenAI


DESCRIPTION_INSTRUCTIONS = """
가족 게시물을 장기 기억 그래프에 저장할 한국어 기록으로 작성한다.
원문과 첨부된 모든 사진을 순서대로 함께 참고하여 작성자가 전하는 소식과 그 맥락을 구체적으로 설명한다.
여러 사진 속 장면을 근거 없이 같은 사건이나 인물로 연결하지 않는다. 사진이 없으면 원문만 사용한다.
은어와 모호한 대상은 근거 없이 뜻을 확정하지 않고 필요한 경우 원문 표현을 유지한다.

원문을 기본 기록으로 삼고, 이미지에서 명확히 확인되는 정보로 원문의 내용을 구체화한다.
다만, 이미지 내의 너무 자세한 내용은 굳이 기록할 필요 없다.
이미지 내에서 저장할 만한 내용이 있으면 함께 기록해도 좋다.
원문을 이해하는 데 도움이 되지 않는 시각적 세부사항은 제외한다.
이미지로 확인할 수 없는 내용은 추측하지 않고 원문 표현을 유지한다.
""".strip()


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
            model=settings.OPENAI_MODEL, instructions=DESCRIPTION_INSTRUCTIONS,
            input=[{"role": "user", "content": content}],
            max_output_tokens=2000, store=False,
        )
    if response.status != "completed" or not response.output_text.strip():
        raise RuntimeError("게시물 상세 설명이 완료되지 않았습니다.")
    return response.output_text.strip()
