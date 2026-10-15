"""A shared, bounded search pool; requests wait for their results."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from django.conf import settings


SEARCH_POOL = ThreadPoolExecutor(max_workers=settings.GRAPHITI_SEARCH_WORKERS)


class SearchUnavailable(Exception):
    pass


def search_history(family_id, question):
    return run_search("family_history", family_id, question)


def search_queries(family_id, queries):
    return run_search("memories", family_id, queries)


def run_search(feature, family_id, value, *, images=()):
    try:
        return SEARCH_POOL.submit(search_worker, feature, family_id, value, images).result()
    except Exception as error:
        logging.getLogger(__name__).exception("Family history search failed")
        raise SearchUnavailable from error


def search_worker(feature, family_id, value, images=()):
    from .graphiti_client import create_graphiti

    # A driver and its SDK client belong to this worker's event loop.
    graphiti = create_graphiti()
    return asyncio.run(search_and_close(graphiti, feature, family_id, value, images))


async def search_and_close(graphiti, feature, family_id, value, images=()):
    from integrations.ai.flow import answer_with_memory
    from .graphiti_client import close_graphiti, family_group
    from .searching_graphiti import search_many

    try:
        family_group(family_id)
        search = partial(search_many, graphiti, family_id)
        if feature == "memories":
            return {"results": await search(value)}
        return await answer_with_memory(search, value, feature, images=images)
    finally:
        await close_graphiti(graphiti)
