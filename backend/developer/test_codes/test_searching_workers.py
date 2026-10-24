"""Worker lifetime, concurrency, and shutdown without external API calls."""

import asyncio
import runpy
from threading import Barrier, Event, get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from integrations.ai import post_flow
from integrations.ai_workers import graphiti_client, searching_graphiti, searching_workers


class SearchWorkerTests(SimpleTestCase):
    def test_server_entrypoints_start_search_pool_before_returning_application(self):
        for protocol in ("wsgi", "asgi"):
            with self.subTest(protocol=protocol), \
                 patch(f"django.core.{protocol}.get_{protocol}_application") as application, \
                 patch.object(searching_workers.SEARCH_POOL, "start") as start:
                module = runpy.run_module(f"configs.{protocol}")
                application.assert_called_once_with()
                start.assert_called_once_with()
                self.assertIs(module["application"], application.return_value)

    def test_start_creates_all_clients_before_any_request_and_is_idempotent(self):
        with patch.object(graphiti_client, "create_graphiti", side_effect=object) as factory, \
             patch.object(searching_graphiti, "search_many", new=AsyncMock()) as search, \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as cleanup:
            with searching_workers.SearchPool(2) as pool:
                pool.start()
                self.assertEqual(factory.call_count, 2)
                search.assert_not_awaited()
                cleanup.assert_not_awaited()
            self.assertEqual(cleanup.await_count, 2)

    def test_reuses_client_and_loop_across_requests_and_family_scopes(self):
        calls = []

        def create():
            return SimpleNamespace(loop=asyncio.get_running_loop(), thread=get_ident())

        async def search(graph, family_id, queries, *, max_queries):
            self.assertIs(asyncio.get_running_loop(), graph.loop)
            self.assertEqual(get_ident(), graph.thread)
            calls.append((family_id, queries, max_queries))
            return queries

        async def close(graph):
            self.assertIs(asyncio.get_running_loop(), graph.loop)
            self.assertEqual(get_ident(), graph.thread)

        async def answer(search, value, feature, *, images):
            return await search([value])

        with patch.object(graphiti_client, "create_graphiti", side_effect=create) as factory, \
             patch.object(searching_graphiti, "search_many", new=AsyncMock(side_effect=search)), \
             patch.object(post_flow, "answer", new=AsyncMock(side_effect=answer)), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock(side_effect=close)) as cleanup:
            with searching_workers.SearchPool(1) as pool:
                self.assertEqual(pool.submit("memories", 1, ["first"]).result(timeout=3),
                                 {"results": ["first"]})
                self.assertEqual(pool.submit("memories", 2, ["second"]).result(timeout=3),
                                 {"results": ["second"]})
                self.assertEqual(pool.submit("post_qa", 3, "qa").result(timeout=3), ["qa"])
                self.assertEqual(pool.submit("memories", 1, ["last"]).result(timeout=3),
                                 {"results": ["last"]})
                factory.assert_called_once()
                cleanup.assert_not_awaited()
            graph = cleanup.await_args.args[0]
            cleanup.assert_awaited_once_with(graph)
            self.assertTrue(graph.loop.is_closed())
        self.assertEqual(calls, [(1, ["first"], 3), (2, ["second"], 3),
                                 (3, ["qa"], 5), (1, ["last"], 3)])

    def test_workers_run_in_parallel_with_separate_clients_and_loops(self):
        both_started = Barrier(2, timeout=3)

        def create():
            return SimpleNamespace(loop=asyncio.get_running_loop(), thread=get_ident())

        async def search(graph, family_id, queries, *, max_queries):
            both_started.wait()
            self.assertIs(asyncio.get_running_loop(), graph.loop)
            return graph

        with patch.object(graphiti_client, "create_graphiti", side_effect=create) as factory, \
             patch.object(searching_graphiti, "search_many", new=AsyncMock(side_effect=search)), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as cleanup:
            with searching_workers.SearchPool(2) as pool:
                first = pool.submit("memories", 1, ["first"])
                second = pool.submit("memories", 2, ["second"])
                graphs = [future.result(timeout=5)["results"] for future in (first, second)]
                self.assertIsNot(graphs[0], graphs[1])
                self.assertIsNot(graphs[0].loop, graphs[1].loop)
                self.assertNotEqual(graphs[0].thread, graphs[1].thread)
                self.assertEqual(factory.call_count, 2)
            self.assertEqual(cleanup.await_count, 2)
            self.assertTrue(all(graph.loop.is_closed() for graph in graphs))

    def test_failed_search_does_not_close_shared_client_or_stop_worker(self):
        with patch.object(graphiti_client, "create_graphiti", return_value="graph") as factory, \
             patch.object(searching_graphiti, "search_many",
                          new=AsyncMock(side_effect=[RuntimeError("offline"), []])) as search, \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as cleanup:
            with searching_workers.SearchPool(1) as pool, \
                 patch.object(searching_workers, "SEARCH_POOL", pool):
                with self.assertLogs(searching_workers.__name__, level="ERROR"), \
                     self.assertRaises(searching_workers.SearchUnavailable):
                    searching_workers.search_queries(1, ["first"])
                self.assertEqual(searching_workers.search_queries(2, ["second"]), {"results": []})
                factory.assert_called_once()
                self.assertEqual(search.await_count, 2)
                cleanup.assert_not_awaited()
            cleanup.assert_awaited_once_with("graph")

    def test_startup_failure_closes_initialized_clients_and_stops_the_pool(self):
        with patch.object(graphiti_client, "create_graphiti",
                          side_effect=["graph", ValueError("missing credentials")]) as factory, \
             patch.object(searching_graphiti, "search_many", new=AsyncMock(return_value=[])), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as cleanup:
            pool = searching_workers.SearchPool(2)
            with self.assertRaisesMessage(ValueError, "missing credentials"):
                pool.start()
            self.assertEqual(factory.call_count, 2)
            self.assertTrue(all(not thread.is_alive() for thread in pool._threads))
            with self.assertRaises(RuntimeError):
                pool.submit("memories", 1, ["after failed startup"])
            cleanup.assert_awaited_once_with("graph")

    def test_no_search_answers_and_invalid_family_reuse_prepared_client(self):
        with patch.object(graphiti_client, "create_graphiti") as factory, \
             patch.object(post_flow, "answer", new=AsyncMock(return_value={"text": "direct"})) as answer, \
             patch.object(searching_graphiti, "search_many", new=AsyncMock()) as search, \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()), \
             searching_workers.SearchPool(1) as pool:
            factory.assert_called_once()
            for feature in ("post_summary", "post_qa"):
                self.assertEqual(pool.submit(feature, 1, "question", ("photo",)).result(timeout=3),
                                 {"text": "direct"})
            with self.assertRaises(ValueError):
                pool.submit("memories", True, ["invalid family"]).result(timeout=3)
            factory.assert_called_once()
            search.assert_not_awaited()
            self.assertEqual(answer.await_count, 2)
            self.assertEqual(answer.await_args.kwargs["images"], ("photo",))

    def test_shutdown_drains_requests_in_order_and_skips_cancelled_work(self):
        started, release = Event(), Event()
        queries_seen = []

        async def search(graph, family_id, queries, *, max_queries):
            queries_seen.extend(queries)
            if queries == ["first"]:
                started.set()
                if not release.wait(timeout=3):
                    raise TimeoutError("test did not release first request")
            return queries

        with patch.object(graphiti_client, "create_graphiti", return_value="graph") as factory, \
             patch.object(searching_graphiti, "search_many", new=AsyncMock(side_effect=search)), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as cleanup:
            with searching_workers.SearchPool(1) as pool:
                first = pool.submit("memories", 1, ["first"])
                try:
                    self.assertTrue(started.wait(timeout=3))
                    cancelled = pool.submit("memories", 1, ["cancelled"])
                    last = pool.submit("memories", 2, ["last"])
                    self.assertTrue(cancelled.cancel())
                    pool.shutdown(wait=False)
                    with self.assertRaises(RuntimeError):
                        pool.submit("memories", 1, ["after shutdown"])
                    cleanup.assert_not_awaited()
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=3), {"results": ["first"]})
                self.assertEqual(last.result(timeout=3), {"results": ["last"]})
            self.assertEqual(queries_seen, ["first", "last"])
            factory.assert_called_once()
            cleanup.assert_awaited_once_with("graph")
