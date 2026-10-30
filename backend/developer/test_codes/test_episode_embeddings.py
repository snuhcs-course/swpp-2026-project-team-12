"""Episode embedding persistence and retrieval without live AI or Neo4j."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from django.test import SimpleTestCase
from django.utils import timezone
from graphiti_core.nodes import EpisodeType, EpisodicNode

from integrations.ai_workers import construction_graphiti, episode_embeddings, searching_graphiti


class EpisodeEmbeddingTests(SimpleTestCase):
    def graph(self, records=()):
        return SimpleNamespace(
            embedder=SimpleNamespace(
                create=AsyncMock(return_value=[1.0, 0.0]),
                create_batch=AsyncMock(return_value=[[1.0, 0.0]]),
            ),
            driver=SimpleNamespace(execute_query=AsyncMock(return_value=(list(records), None, None))),
            search_=AsyncMock(return_value=SimpleNamespace(edges=[], episodes=[])),
        )

    def episode(self, uuid="episode", **changes):
        return EpisodicNode(
            uuid=uuid, name="post_20", group_id="family_1", source=EpisodeType.text,
            source_description="토닥 기록", valid_at=timezone.now(),
            content=changes.pop("content", "작성자: 민수\n상세 설명: 모모라는 강아지를 입양했다."),
            **changes,
        )

    def test_new_memory_embeds_the_description_and_saves_it_on_the_episode(self):
        episode = self.episode()
        graph = self.graph()
        graph.add_episode = AsyncMock(return_value=SimpleNamespace(episode=episode))
        result = asyncio.run(construction_graphiti.add_memory(
            graph, 1, episode.content, episode.name, episode.valid_at,
        ))
        self.assertEqual(result, episode.uuid)
        graph.embedder.create_batch.assert_awaited_once_with([episode.content])
        params = graph.driver.execute_query.await_args.kwargs
        self.assertEqual(params["group_id"], "family_1")
        self.assertEqual(params["episodes"], [{
            "uuid": episode.uuid, "content": episode.content, "embedding": [1.0, 0.0],
        }])

    def test_worker_backfills_existing_episodes_without_reconstructing_facts(self):
        episode = self.episode()
        records = [
            {"uuid": episode.uuid, "name": episode.name, "content": episode.content},
            {"uuid": "already-embedded", "name": "post_21", "content": None},
            {"uuid": "registry", "name": "family_registry_1_v1", "content": None},
        ]
        graph = self.graph(records)
        graph.add_episode = AsyncMock()
        names = asyncio.run(construction_graphiti.episode_names(graph, 1))
        self.assertEqual(names, {r["name"] for r in records})
        graph.embedder.create_batch.assert_awaited_once_with([episode.content])
        graph.add_episode.assert_not_awaited()

    def test_failed_backfill_is_retried_and_does_not_mark_the_embedding_saved(self):
        episode = self.episode()
        graph = self.graph([{"uuid": episode.uuid, "name": episode.name, "content": episode.content}])
        graph.embedder.create_batch.side_effect = [RuntimeError("offline"), [[1.0, 0.0]]]
        with self.assertRaisesMessage(RuntimeError, "offline"):
            asyncio.run(construction_graphiti.episode_names(graph, 1))
        self.assertEqual(graph.driver.execute_query.await_count, 1)
        self.assertEqual(asyncio.run(construction_graphiti.episode_names(graph, 1)), {episode.name})
        self.assertEqual(graph.driver.execute_query.await_count, 3)

    def test_embedding_count_mismatch_does_not_partially_write_a_batch(self):
        graph = self.graph()
        graph.embedder.create_batch.return_value = []
        with self.assertRaises(ValueError):
            asyncio.run(episode_embeddings.embed_episodes(graph, "family_1", [
                {"uuid": "episode", "content": "상세 설명"},
            ]))
        graph.driver.execute_query.assert_not_awaited()

    def test_vector_only_episode_reaches_the_answer_context_without_edges(self):
        episode = self.episode()
        graph = self.graph([{**episode.model_dump(), "source": episode.source.value}])
        result, = asyncio.run(searching_graphiti.search_many(graph, 1, ["반려견을 데려온 이야기"]))
        memory, = result["memories"]
        self.assertEqual(memory["fact"], episode.content)
        self.assertEqual(memory["source_episode_ids"], [episode.uuid])
        self.assertEqual(memory["sources"][0]["text"], episode.content)
        self.assertIsNone(memory["valid_at"])
        graph.embedder.create.assert_awaited_once()
        self.assertEqual(graph.search_.await_args.kwargs["query_vector"], [1.0, 0.0])
        query = graph.driver.execute_query.await_args
        self.assertIn("vector.similarity.cosine", query.args[0])
        self.assertEqual(query.kwargs["group_id"], "family_1")
        self.assertEqual(query.kwargs["query_vector"], [1.0, 0.0])
        self.assertEqual(query.kwargs["min_score"], searching_graphiti.SEARCH_CONFIG.episode_config.sim_min_score)

    def test_hybrid_search_deduplicates_and_excludes_other_families(self):
        shared = self.episode()
        vector_only = self.episode("vector-only")
        foreign = shared.model_copy(update={"uuid": "foreign", "group_id": "family_2"})
        graph = self.graph([{**e.model_dump(), "source": e.source.value}
                            for e in [shared, vector_only, foreign]])
        graph.search_.return_value.episodes = [shared, foreign]
        result, = asyncio.run(searching_graphiti.search_many(graph, 1, ["반려견"]))
        self.assertEqual([m["id"] for m in result["memories"]], [shared.uuid, vector_only.uuid])

    def test_vector_failure_cancels_the_graph_search_before_returning(self):
        async def run():
            graph = self.graph()
            started, cancelled = asyncio.Event(), asyncio.Event()

            async def search(**kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

            async def query(*args, **kwargs):
                await started.wait()
                raise RuntimeError("offline")

            graph.search_.side_effect = search
            graph.driver.execute_query.side_effect = query
            with self.assertRaises(ExceptionGroup):
                await searching_graphiti.search_many(graph, 1, ["반려견"])
            self.assertTrue(cancelled.is_set())

        asyncio.run(run())
