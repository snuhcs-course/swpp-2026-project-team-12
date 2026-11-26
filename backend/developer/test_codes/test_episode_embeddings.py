"""Episode embedding persistence and retrieval without live AI or Neo4j."""

import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase
from django.utils import timezone
from graphiti_core.nodes import EpisodeType, EpisodicNode

from integrations.ai_workers import construction_graphiti, episode_embeddings, post_evidence, searching_graphiti
from integrations.ai_workers.temporal_search import date_preference, time_rank


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

    def test_qa_uses_inflected_action_and_subject_to_find_lexical_evidence(self):
        graph = self.graph()
        question = "유나가 예약했던 장소와 건우가 취소한 일정은?"
        with patch.object(episode_embeddings, "fulltext_query",
                          return_value='group_id:"family_1" AND (escaped question)'):
            asyncio.run(searching_graphiti.search_many(graph, 1, [question], question=question))

        lexical_call = next(call for call in graph.driver.execute_query.await_args_list
                            if "fulltext.queryNodes" in call.args[0])
        self.assertEqual(lexical_call.kwargs["query"],
                         'group_id:"family_1" AND (escaped question 예약* (유나* AND 예약*)^2 취소* (건우* AND 취소*)^2)')
        self.assertEqual(lexical_call.kwargs["group_id"], "family_1")
        self.assertIsNone(graph.search_.await_args.kwargs["config"].episode_config)
        graph.embedder.create.assert_awaited_once()

    def test_explicit_event_day_keeps_older_episodes_and_facts(self):
        now = datetime.fromisoformat("2026-10-16T01:00:00+09:00")
        earlier = now - timedelta(days=3)
        episode = self.episode().model_copy(update={"valid_at": earlier})
        graph = self.graph([{**episode.model_dump(), "source": episode.source.value}])
        graph.search_.return_value.edges = [SimpleNamespace(
            uuid="fact", group_id="family_1", fact="일정", valid_at=earlier, invalid_at=None, episodes=[episode.uuid],
        )]
        result, = asyncio.run(searching_graphiti.search_many(
            graph, 1, ["한 일 확인"], question="10월 15일에 뭐 했지?", reference_time=now,
        ))
        graph_args = graph.search_.await_args.kwargs
        self.assertIsNotNone(graph_args["config"].episode_config)
        self.assertNotIn("search_filter", graph_args)
        self.assertIsNone(graph.driver.execute_query.await_args.kwargs["cutoff"])
        self.assertEqual(result["memories"][0]["sources"][0]["id"], episode.uuid)

    def test_as_of_search_keeps_prior_post_and_drops_facts_with_later_sources(self):
        now = datetime.fromisoformat("2026-10-18T18:00:00+09:00")
        earlier = now - timedelta(days=4)
        post = self.episode("past").model_copy(update={"valid_at": earlier})
        graph = self.graph()
        graph.search_.return_value.edges = [
            SimpleNamespace(uuid=key, group_id="family_1", fact=key, valid_at=now, invalid_at=now, episodes=source_ids)
            for key, source_ids in [("planned", ["past"]), ("later", ["future"]), ("changed", ["past", "future"])]
        ]

        async def query(cypher, **options):
            if "e.uuid AS id" in cypher:
                rows = [{"id": "past"}]
            elif "vector.similarity.cosine" in cypher:
                rows = [{**post.model_dump(), "source": post.source.value}]
            else:
                rows = []
            return rows, None, None

        graph.driver.execute_query.side_effect = query
        with patch.object(episode_embeddings, "fulltext_query", return_value="query"):
            result, = asyncio.run(searching_graphiti.search_many(
                graph, 1, ["누가 맡았어?"], question="10월 17일 기준 누가 맡기로 했어?", reference_time=now,
            ))
        only, = result["memories"]
        self.assertEqual(only["id"], "planned")
        self.assertEqual(only["sources"][0]["id"], "past")
        self.assertIsNone(only["invalid_at"])
        for call in graph.driver.execute_query.await_args_list:
            self.assertIn("e.valid_at <= $cutoff", call.args[0])
            self.assertEqual(call.kwargs["cutoff"], datetime.fromisoformat("2026-10-17T23:59:59.999999+09:00"))

    def test_post_prefetch_uses_original_as_of_date_for_each_derived_query(self):
        now = datetime.fromisoformat("2026-10-18T18:00:00+09:00")
        graph = self.graph()
        graph.embedder.create_batch.return_value = [[1.0, 0.0], [0.0, 1.0]]
        graph.driver.execute_query.return_value = ([{"rankings": [], "sources": []}], None, None)
        with patch.object(post_evidence.timezone, "now", return_value=now), \
             patch.object(post_evidence, "fulltext_query", return_value="query"):
            asyncio.run(post_evidence.prefetch_post_episodes(
                graph, 1, ["담당자", "청소"], question="10월 17일 기준 청소 담당자는?", exclude_post="post_30",
            ))
        call = graph.driver.execute_query.await_args
        self.assertEqual(call.kwargs["exclude_post"], "post_30")
        self.assertEqual(call.args[0].count("e.valid_at <= candidate.cutoff"), 2)
        cutoff = datetime.fromisoformat("2026-10-17T23:59:59.999999+09:00")
        self.assertEqual([query["cutoff"] for query in call.kwargs["queries"]], [cutoff, cutoff])

    def test_post_search_excludes_the_current_episode_before_selecting_facts_and_posts(self):
        graph = self.graph()
        graph.driver.execute_query.side_effect = [([{"id": "current"}], None, None), ([], None, None), ([], None, None)]
        graph.search_.return_value.edges = [
            SimpleNamespace(uuid=key, group_id="family_1", fact=key, valid_at=None, invalid_at=None, episodes=ids)
            for key, ids in [("current_fact", ["current"]), ("merged_fact", ["current", "older"]), ("other_fact", [])]
        ]
        with patch.object(episode_embeddings, "fulltext_query", return_value="query"):
            result, = asyncio.run(searching_graphiti.search_many(graph, 1, ["질문"], exclude_post="post_20"))
        self.assertEqual([m["id"] for m in result["memories"]], ["other_fact"])
        self.assertEqual(graph.driver.execute_query.await_args_list[0].kwargs["name"], "post_20")
        for call in graph.driver.execute_query.await_args_list[1:]:
            self.assertIn("e.name <> $exclude_post", call.args[0].split("LIMIT")[0])
            self.assertEqual(call.kwargs["exclude_post"], "post_20")

    def test_relative_and_approximate_event_dates_use_korean_calendar_days(self):
        now = datetime.fromisoformat("2026-10-15T16:00:00+00:00")
        start = datetime.fromisoformat("2026-10-15T00:00:00+09:00")
        preference = date_preference("어제 뭐 했지?", now)
        self.assertEqual(preference.day, date(2026, 10, 15))
        self.assertEqual(date_preference("10월 15일쯤 무슨 일이 있었어?", now), preference)
        self.assertEqual(date_preference("10월 15일 약속이 몇 시야?", now), preference)
        self.assertIsNone(preference.cutoff)
        self.assertIsNone(date_preference("10월 15일부터 18일까지 뭐 했지?", now))
        self.assertEqual(date_preference("오늘 기준 누가 맡았어?", now).cutoff, now)
        self.assertGreater(time_rank(0.2, start, now, preference),
                           time_rank(0.2, start - timedelta(days=1), now, preference))
        self.assertGreater(time_rank(1.0, start - timedelta(days=7), now, preference),
                           time_rank(0.2, start, now, preference))

    def test_recency_breaks_close_fact_scores_without_overriding_strong_matches(self):
        now = datetime.fromisoformat("2026-10-16T01:00:00+09:00")
        strong, older, recent = [
            SimpleNamespace(uuid=name, fact=name, group_id="family_1", episodes=[],
                            valid_at=now - timedelta(days=age), invalid_at=None)
            for name, age in [("strong", 30), ("older", 30), ("recent", 1)]
        ]
        graph = self.graph()
        graph.search_.return_value = SimpleNamespace(
            edges=[strong, older, recent], edge_reranker_scores=[0.5, 0.2, 0.18], episodes=[],
        )
        result, = asyncio.run(searching_graphiti.search_many(
            graph, 1, ["장소"], reference_time=now,
        ))
        self.assertEqual([memory["id"] for memory in result["memories"]], ["strong", "recent", "older"])

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
