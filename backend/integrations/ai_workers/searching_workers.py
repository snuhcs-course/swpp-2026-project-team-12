"""A shared search pool with one event loop and Graphiti client per worker."""

import atexit
import asyncio
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

            async def search(family_id, queries, *, max_queries=3):
                from .searching_graphiti import search_many

                return await search_many(graphiti, family_id, queries, max_queries=max_queries)

            try:
                while True:
                    request = queue.get()
                    if request is None:
                        return
                    future, feature, family_id, value, images = request
                    if not future.set_running_or_notify_cancel():
                        continue
                    try:
                        result = runner.run(answer_request(search, feature, family_id, value, images))
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


async def answer_request(search, feature, family_id, value, images=()):
    from .graphiti_client import family_group

    family_group(family_id)
    search = partial(search, family_id)
    if feature in {"post_summary", "post_qa"}:
        from integrations.ai.post_flow import answer
        from integrations.ai.prompts import MAX_QUERIES

        return await answer(partial(search, max_queries=MAX_QUERIES), value, feature, images=images)
    if feature == "memories":
        return {"results": await search(value)}

    from integrations.ai.flow import answer_with_memory

    return await answer_with_memory(search, value, feature, images=images)


SEARCH_POOL = SearchPool(settings.GRAPHITI_SEARCH_WORKERS)
atexit.register(SEARCH_POOL.shutdown)
