"""A shared search pool with one event loop and Graphiti client per worker."""

import atexit
import asyncio
import json
import logging
from concurrent.futures import Future
from contextvars import copy_context
import time
from integrations.telemetry import stage, runtime, emit
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
        self._queue.active = 0
        self._queue.active_lock = Lock()
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
        runtime("search", configured=self._max_workers, alive=sum(thread.is_alive() for thread in self._threads))
        report_pool(self._queue)
        return self

    def submit(self, feature, family_id, value, images=()):
        self.start()
        future = Future()
        future.telemetry_context = copy_context()
        future.queued_at = time.monotonic()
        with self._lock:
            if self._shutdown:
                raise RuntimeError("Cannot submit searches after shutdown")
            self._queue.put((future, feature, family_id, value, images))
            emit("search_queued", component="search", feature=feature, result="success")
            report_pool(self._queue)
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


def report_pool(queue):
    with queue.mutex:
        requests = [row for row in queue.queue if row is not None]
    oldest = min((row[0].queued_at for row in requests), default=time.monotonic())
    runtime("search", waiting=len(requests), running=queue.active,
            oldest_monotonic=oldest, last_poll=time.time())


def search_worker(queue, ready):
    try:
        from .graphiti_client import close_graphiti, initialize_graphiti

        with asyncio.Runner() as runner:
            graphiti = runner.run(initialize_graphiti())
            ready.set_result(None)

            async def search(family_id, queries, *, max_queries=3, **options):
                from .searching_graphiti import search_many

                with stage("graphiti_search"):
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
                        report_pool(queue)
                        future.telemetry_context.run(emit, "search_cancelled", component="search", result="cancelled")
                        continue
                    with queue.active_lock:
                        queue.active += 1
                        report_pool(queue)
                    def execute():
                        from integrations.telemetry import emit, bind
                        with bind(component="search", feature=feature):
                            emit("queue_wait", result="success", duration_ms=(time.monotonic() - future.queued_at) * 1000)
                            with stage("search_execution"):
                                return runner.run(answer_request(search, feature, family_id, value, images, prefetch_posts=prefetch_posts))
                    try:
                        result = future.telemetry_context.run(execute)
                    except BaseException as error:
                        future.set_exception(error)
                    else:
                        future.set_result(result)
                    finally:
                        with queue.active_lock:
                            queue.active -= 1
                            report_pool(queue)
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

    async def search_posts(queries, **options):
        from .post_evidence import attach_post_fields

        results = await search(queries, **options)
        sources = [source for result in results for memory in result["memories"]
                   for source in memory.get("sources", ())]
        await attach_post_fields(family_id, sources)
        return results

    if feature in {"post_summary", "post_qa"}:
        from integrations.ai.post_flow import answer
        from integrations.ai.prompts import MAX_QUERIES

        options = {}
        answer_options = {"images": images}
        if feature == "post_qa":
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

    if feature == "family_history":
        return await answer_with_memory(partial(search_posts, question=value), value, feature, images=images)
    return await answer_with_memory(search, value, feature, images=images)


SEARCH_POOL = SearchPool(settings.GRAPHITI_SEARCH_WORKERS)
atexit.register(SEARCH_POOL.shutdown)
