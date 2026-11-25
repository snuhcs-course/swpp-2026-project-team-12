"""A shared search pool with one event loop and Graphiti client per worker."""

import atexit
import asyncio
import json
import logging
from concurrent.futures import Future
from functools import partial
from queue import Queue
from threading import Lock, Thread

from django.conf import settings


class SearchPool:
    def __init__(self, max_workers):
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than 0")
        self._max_workers = max_workers
        self._queue = Queue()
        self._threads = []
        self._ready = []
        self._lock = Lock()
        self._shutdown = False

    def start(self):
        with self._lock:
            if self._shutdown:
                raise RuntimeError("Cannot start searches after shutdown")
            if not self._threads:
                for index in range(self._max_workers):
                    ready = Future()
                    thread = Thread(target=search_worker, args=(self._queue, ready),
                                    name=f"graphiti-search-{index}", daemon=True)
                    thread.start()
                    self._threads.append(thread)
                    self._ready.append(ready)
        try:
            # Do not accept requests until every worker has created its client.
            for ready in self._ready:
                ready.result()
        except BaseException:
            self.shutdown()
            raise
        return self

    def submit(self, feature, family_id, value, images=()):
        self.start()
        future = Future()
        with self._lock:
            if self._shutdown:
                raise RuntimeError("Cannot submit searches after shutdown")
            self._queue.put((future, feature, family_id, value, images))
        return future

    def shutdown(self, wait=True):
        with self._lock:
            if not self._shutdown:
                self._shutdown = True
                # FIFO stop markers let workers finish all submitted requests first.
                for _ in self._threads:
                    self._queue.put(None)
        if wait:
            for thread in self._threads:
                thread.join()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.shutdown()


class SearchUnavailable(Exception):
    pass


def search_history(family_id, question):
    return run_search("family_history", family_id, question)


def search_queries(family_id, queries):
    return run_search("memories", family_id, queries)


def run_search(feature, family_id, value, *, images=()):
    try:
        return SEARCH_POOL.submit(feature, family_id, value, images).result()
    except Exception as error:
        logging.getLogger(__name__).exception("Family history search failed")
        raise SearchUnavailable from error


def search_worker(queue, ready):
    try:
        from .graphiti_client import close_graphiti, initialize_graphiti

        with asyncio.Runner() as runner:
            graphiti = runner.run(initialize_graphiti())
            ready.set_result(None)

            async def search(family_id, queries, *, max_queries=3, **options):
                from .searching_graphiti import search_many

                return await search_many(graphiti, family_id, queries, max_queries=max_queries, **options)

            async def prefetch_posts(family_id, queries, **options):
                from .post_evidence import prefetch_post_episodes

                return await prefetch_post_episodes(graphiti, family_id, queries, **options)

            try:
                while True:
                    request = queue.get()
                    if request is None:
                        return
                    future, feature, family_id, value, images = request
                    if not future.set_running_or_notify_cancel():
                        continue
                    try:
                        result = runner.run(answer_request(search, feature, family_id, value, images, prefetch_posts=prefetch_posts))
                    except BaseException as error:
                        future.set_exception(error)
                    else:
                        future.set_result(result)
            finally:
                runner.run(close_graphiti(graphiti))
    except BaseException as error:
        if not ready.done():
            ready.set_exception(error)
        else:
            logging.getLogger(__name__).exception("Search worker stopped unexpectedly")


async def answer_request(search, feature, family_id, value, images=(), *, prefetch_posts=None):
    from .graphiti_client import family_group

    family_group(family_id)
    search = partial(search, family_id)
    if feature in {"post_summary", "post_qa"}:
        from integrations.ai.post_flow import answer
        from integrations.ai.prompts import MAX_QUERIES

        options = {}
        answer_options = {"images": images}
        if feature == "post_qa":
            from .post_evidence import attach_post_fields

            async def search_posts(queries, **options):
                results = await search(queries, **options)
                sources = [source for result in results for memory in result["memories"]
                           for source in memory.get("sources", ())]
                await attach_post_fields(family_id, sources)
                return results

            try:
                payload = json.loads(value)
            except (TypeError, ValueError):
                payload = None
            if isinstance(payload, dict):
                post_id = payload.pop("게시글 ID", None)
                if type(post_id) is int and post_id > 0:
                    options["exclude_post"] = f"post_{post_id}"
                    value = json.dumps(payload, ensure_ascii=False)
                if isinstance(payload.get("질문"), str):
                    options["question"] = payload["질문"]
                    if prefetch_posts is not None:
                        answer_options["prefetch"] = partial(prefetch_posts, family_id, **options)
                    answer_options["retry_search"] = partial(search_posts, max_queries=MAX_QUERIES, prefer_semantic=True,
                                                              **options)
                if parent_terms := payload.get("확인된 가족 호칭"):
                    answer_options["parent_terms"] = parent_terms
            return await answer(partial(search_posts, max_queries=MAX_QUERIES, **options), value, feature, **answer_options)
        return await answer(partial(search, max_queries=MAX_QUERIES), value, feature, **answer_options)
    if feature == "memories":
        return {"results": await search(value)}

    from integrations.ai.flow import answer_with_memory

    return await answer_with_memory(search, value, feature, images=images)


SEARCH_POOL = SearchPool(settings.GRAPHITI_SEARCH_WORKERS)
atexit.register(SEARCH_POOL.shutdown)
