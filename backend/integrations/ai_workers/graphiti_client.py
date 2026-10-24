"""Shared Graphiti client lifecycle and server-selected family scope."""

from django.conf import settings
from graphiti_core import Graphiti
from graphiti_core.cross_encoder import OpenAIRerankerClient
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client import LLMConfig, OpenAIClient
from openai import AsyncOpenAI


def create_graphiti():
    if not settings.OPENAI_API_KEY or not settings.NEO4J_PASSWORD:
        raise ValueError(".env에 OPENAI_API_KEY와 NEO4J_PASSWORD를 설정하세요.")
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=1)
    config = LLMConfig(api_key=settings.OPENAI_API_KEY, model=settings.GRAPHITI_MODEL,
                       small_model=settings.GRAPHITI_MODEL)
    return Graphiti(
        uri=settings.NEO4J_URI, user=settings.NEO4J_USER, password=settings.NEO4J_PASSWORD,
        llm_client=OpenAIClient(config=config, client=client),
        embedder=OpenAIEmbedder(config=OpenAIEmbedderConfig(
            api_key=settings.OPENAI_API_KEY, embedding_model="text-embedding-3-small",
        ), client=client),
        cross_encoder=OpenAIRerankerClient(config=config, client=client),
    )


async def initialize_graphiti():
    return create_graphiti()


async def close_graphiti(graphiti):
    try:
        await graphiti.close()
    finally:
        await graphiti.llm_client.client.close()


def family_group(family_id):
    if not isinstance(family_id, int) or isinstance(family_id, bool) or family_id <= 0:
        raise ValueError("family_id는 양의 정수여야 합니다.")
    return f"family_{family_id}"
