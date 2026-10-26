import asyncio
import base64
import io
import json
import os
import tempfile
from datetime import timedelta
from functools import partial
from statistics import mean
from time import perf_counter
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import AsyncMock, patch

from django.core.management import call_command
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import Post
from apps.searching import services
from integrations.ai import feed_description, flow, prompts, provider
from integrations.ai_workers import construction_graphiti, graphiti_client, searching_graphiti, searching_workers

from .family_fixtures import auth_headers, add_member


class FamilyFixture:
    def setUp(self):
        self.user = User.objects.create_user(username="history", display_name="정아")
        self.room = FamilyRoom.objects.create(
            owner=self.user, name="정아네", invite_code="HIST01", password_hash="hashed", graph_synced_version=0,
        )
        add_member(self.room, self.user)
        self.auth = auth_headers(AccessToken.issue(self.user))

    def post(self, path, data):
        return self.client.post(path, json.dumps(data), content_type="application/json", **self.auth)


class HistoryAPITests(FamilyFixture, TestCase):
    def test_history_selects_authenticated_family_and_waits_for_answer(self):
        result = {"text": "준하의 엄마는 수진, 아빠는 도윤이에요.", "query": "준하의 부모", "memories": []}
        with patch.object(services, "search_history", return_value=result) as search:
            response = self.post("/api/searching/history/", {"question": " 준하의 부모 ", "family_id": 999})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        self.assertEqual(response["Cache-Control"], "no-store")
        search.assert_called_once_with(self.room.pk, "준하의 부모")

    def test_authentication_membership_and_input_fail_before_search(self):
        path = "/api/searching/history/"
        with patch.object(services, "search_history") as search:
            self.assertEqual(self.client.post(path).status_code, 401)
            self.assertEqual(self.client.get(path, **self.auth).status_code, 405)
            for question in [None, 1, "", "  ", "x" * 1001]:
                self.assertEqual(self.post(path, {"question": question}).status_code, 400)
            self.assertEqual(self.client.post(path, "bad", content_type="application/json", **self.auth).status_code, 400)
            self.assertEqual(self.client.post(path, {}, **self.auth).status_code, 415)
            Membership.objects.all().delete()
            self.assertEqual(self.post(path, {"question": "준하의 부모"}).status_code, 403)
        search.assert_not_called()

    def test_parallel_retrieval_endpoint_and_service_failure(self):
        with patch.object(services, "search_queries", return_value={"results": []}) as search:
            response = self.post("/api/searching/memories/", {"queries": [" 부모 ", "반려견"]})
            self.assertEqual(response.status_code, 200)
            search.assert_called_once_with(self.room.pk, ["부모", "반려견"])
            for queries in [None, "부모", [], ["a"] * 4, [1], [" "]]:
                self.assertEqual(self.post("/api/searching/memories/", {"queries": queries}).status_code, 400)
        with patch.object(services, "search_history", side_effect=services.SearchUnavailable):
            failed = self.post("/api/searching/history/", {"question": "부모"})
        self.assertEqual(failed.status_code, 503)
        self.assertIn("가족 기록", failed.json()["error"])

    def test_construction_is_ordered_scoped_and_resumes_saved_posts(self):
        first = Post.objects.create(room=self.room, author=self.user, caption="처음 기록", images=["test.jpg"])
        second = Post.objects.create(room=self.room, author=self.user, caption="다음 기록", images=["test.jpg"])
        saved = Post.objects.create(room=self.room, author=self.user, caption="저장된 기록", images=["test.jpg"])
        Post.objects.filter(pk=second.pk).update(created_at=first.created_at - timedelta(days=1))
        other = FamilyRoom.objects.create(owner=self.user, name="다른 가족", invite_code="HIST02", password_hash="hashed")
        Post.objects.create(room=other, author=self.user, caption="다른 가족 기록", images=["test.jpg"])
        records = [{"name": f"post_{saved.pk}"}]
        graph = SimpleNamespace(
            build_indices_and_constraints=AsyncMock(),
            driver=SimpleNamespace(execute_query=AsyncMock(return_value=(records, None, None))),
        )

        async def save(graphiti, family_id, text, source, at):
            records.append({"name": source})

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
             patch.object(feed_description, "describe_post", new=AsyncMock(return_value="상세 기록")) as describe, \
             patch.object(graphiti_client, "create_graphiti", return_value=graph), \
             patch.object(construction_graphiti, "add_memory", new=AsyncMock(side_effect=save)) as add, \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as close:
            for _ in range(2):
                call_command("run_construction_worker", family_id=self.room.pk, once=True, stdout=io.StringIO())
        self.assertEqual([call.args[3] for call in add.await_args_list], [f"post_{second.pk}", f"post_{first.pk}"])
        self.assertTrue(all(call.args[1] == self.room.pk for call in add.await_args_list))
        self.assertEqual(add.await_args_list[0].args[4], first.created_at - timedelta(days=1))
        self.assertEqual(close.await_count, 2)
        self.assertEqual(describe.await_count, 2)
        self.assertTrue(all("상세 설명: 상세 기록" in call.args[2] for call in add.await_args_list))
        saved.refresh_from_db()
        self.assertEqual(saved.description, "")

    def test_construction_failure_can_be_retried(self):
        Post.objects.create(room=self.room, author=self.user, caption="기록", images=["test.jpg"])
        graph = SimpleNamespace(
            build_indices_and_constraints=AsyncMock(),
            driver=SimpleNamespace(execute_query=AsyncMock(return_value=([], None, None))),
        )
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
             patch.object(feed_description, "describe_post", new=AsyncMock(return_value="상세 기록")) as describe, \
             patch.object(graphiti_client, "create_graphiti", return_value=graph), \
             patch.object(construction_graphiti, "add_memory", new=AsyncMock(side_effect=[RuntimeError("offline"), "episode"])) as add, \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()):
            with self.assertRaises(CommandError):
                call_command("run_construction_worker", family_id=self.room.pk, once=True, stdout=io.StringIO())
            call_command("run_construction_worker", family_id=self.room.pk, once=True, stdout=io.StringIO())
        self.assertEqual(add.await_count, 2)
        describe.assert_awaited_once()

    def test_construction_creates_and_reuses_client_on_one_loop_across_polls(self):
        post = Post.objects.create(room=self.room, author=self.user, caption="기록",
                                   description="상세 기록", images=["test.jpg"])
        saved = []
        created = []

        def create():
            graph = SimpleNamespace(loop=asyncio.get_running_loop())
            created.append(graph)

            async def build():
                self.assertIs(asyncio.get_running_loop(), graph.loop)

            graph.build_indices_and_constraints = AsyncMock(side_effect=build)
            return graph

        async def names(graph, family_id):
            self.assertIs(graph, created[0])
            self.assertIs(asyncio.get_running_loop(), graph.loop)
            self.assertEqual(family_id, self.room.pk)
            return set(saved)

        async def add(graph, family_id, text, source, at):
            self.assertIs(graph, created[0])
            self.assertIs(asyncio.get_running_loop(), graph.loop)
            saved.append(source)

        async def close(graph):
            self.assertIs(asyncio.get_running_loop(), graph.loop)

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
             patch.object(graphiti_client, "create_graphiti", side_effect=create) as factory, \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock(side_effect=close)) as cleanup, \
             patch.object(construction_graphiti, "episode_names", new=AsyncMock(side_effect=names)) as polls, \
             patch.object(construction_graphiti, "add_memory", new=AsyncMock(side_effect=add)) as store, \
             patch("integrations.ai_workers.construction_workers.time.sleep", side_effect=[None, KeyboardInterrupt]):
            call_command("run_construction_worker", family_id=self.room.pk, stdout=io.StringIO())
        factory.assert_called_once()
        self.assertEqual(polls.await_count, 2)
        store.assert_awaited_once()
        self.assertEqual(saved, [f"post_{post.pk}"])
        cleanup.assert_awaited_once_with(created[0])
        self.assertTrue(created[0].loop.is_closed())

    def test_description_failure_does_not_save_memory_and_can_retry(self):
        post = Post.objects.create(room=self.room, author=self.user, caption="기록", images=["test.jpg"])
        graph = SimpleNamespace(
            build_indices_and_constraints=AsyncMock(),
            driver=SimpleNamespace(execute_query=AsyncMock(return_value=([], None, None))),
        )
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
             patch.object(feed_description, "describe_post", new=AsyncMock(side_effect=[RuntimeError("offline"), "상세 기록"])), \
             patch.object(graphiti_client, "create_graphiti", return_value=graph), \
             patch.object(construction_graphiti, "add_memory", new=AsyncMock()) as add, \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()):
            with self.assertRaises(CommandError):
                call_command("run_construction_worker", family_id=self.room.pk, once=True, stdout=io.StringIO())
            add.assert_not_awaited()
            post.refresh_from_db()
            self.assertEqual(post.description, "")
            call_command("run_construction_worker", family_id=self.room.pk, once=True, stdout=io.StringIO())
        add.assert_awaited_once()
        post.refresh_from_db()
        self.assertEqual(post.description, "상세 기록")

    @override_settings(OPENAI_API_KEY="test-key")
    def test_construction_describes_ordered_photos_and_text_only_posts(self):
        graph = SimpleNamespace(
            build_indices_and_constraints=AsyncMock(),
            driver=SimpleNamespace(execute_query=AsyncMock(return_value=([], None, None))),
        )
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            paths = [default_storage.save(name, ContentFile(content))
                     for name, content in [("cover.jpg", b"cover"), ("second.jpg", b"second"), ("third.jpg", b"third")]]
            post = Post.objects.create(room=self.room, author=self.user, caption="여러 사진의 소식", images=paths)
            text_post = Post.objects.create(room=self.room, author=self.user, caption="글로만 남긴 소식", images=[])
            with patch.object(graphiti_client, "create_graphiti", return_value=graph), \
                 patch.object(graphiti_client, "close_graphiti", new=AsyncMock()), \
                 patch.object(construction_graphiti, "add_memory", new=AsyncMock()) as add, \
                 patch.object(feed_description, "AsyncOpenAI") as sdk:
                client = sdk.return_value.__aenter__.return_value
                client.responses.create = AsyncMock(side_effect=[
                    SimpleNamespace(status="completed", output_text="모든 사진을 반영한 기록"),
                    SimpleNamespace(status="completed", output_text="원문만 반영한 기록"),
                ])
                call_command("run_construction_worker", family_id=self.room.pk, once=True, stdout=io.StringIO())
            inputs = [call.kwargs["input"][0]["content"] for call in client.responses.create.await_args_list]
            self.assertEqual([base64.b64decode(item["image_url"].split(",", 1)[1]) for item in inputs[0][1:]],
                             [b"cover", b"second", b"third"])
            self.assertEqual(len(inputs[1]), 1)
            self.assertEqual(json.loads(inputs[1][0]["text"])["원문"], "글로만 남긴 소식")
            self.assertEqual([call.args[2] for call in add.await_args_list], [
                "작성자: 정아\n상세 설명: 모든 사진을 반영한 기록",
                "작성자: 정아\n상세 설명: 원문만 반영한 기록",
            ])
            post.refresh_from_db()
            text_post.refresh_from_db()
            self.assertEqual(post.description, "모든 사진을 반영한 기록")
            self.assertEqual(text_post.description, "원문만 반영한 기록")

    def test_only_one_local_construction_worker_can_own_a_family(self):
        def start_second_worker(*args):
            with self.assertRaisesMessage(CommandError, "이미 실행 중"):
                call_command("run_construction_worker", family_id=self.room.pk, once=True)

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
             patch("integrations.ai_workers.construction_workers.construct", side_effect=start_second_worker):
            call_command("run_construction_worker", family_id=self.room.pk, once=True)


class MemoryFlowTests(SimpleTestCase):
    def test_two_way_retrieves_before_exactly_one_answer_call(self):
        edge = SimpleNamespace(uuid="fact", group_id="family_1", fact="준하의 부모는 수진과 도윤",
                               valid_at=timezone.now(), invalid_at=None, episodes=["episode"])
        other_edge = SimpleNamespace(**{**vars(edge), "uuid": "other", "group_id": "family_2"})
        source = {"id": "episode", "name": "post_2", "text": "엄마는 수진, 아빠는 도윤", "recorded_at": "2026-09-01"}
        graph = SimpleNamespace(search=AsyncMock(return_value=[edge, other_edge]),
                                driver=SimpleNamespace(execute_query=AsyncMock(return_value=([source], None, None))))
        response = SimpleNamespace(status="completed", output_text="엄마는 수진, 아빠는 도윤이에요.")
        with patch.object(flow, "AsyncOpenAI") as sdk:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=response)
            result = asyncio.run(flow.answer_with_memory(
                partial(searching_graphiti.search_many, graph, 1), "준하의 부모", "family_history",
            ))
        graph.search.assert_awaited_once_with(query="준하의 부모", group_ids=["family_1"], num_results=5)
        self.assertEqual([fact["id"] for fact in result["memories"]], ["fact"])
        self.assertEqual(result["memories"][0]["sources"], [source])
        self.assertEqual(graph.driver.execute_query.call_args.kwargs["group_id"], "family_1")
        client.responses.create.assert_awaited_once()
        self.assertNotIn("tools", client.responses.create.call_args.kwargs)
        self.assertEqual(client.responses.create.call_args.kwargs["instructions"], prompts.HISTORY_INSTRUCTIONS)

    def test_no_evidence_does_not_invent_an_answer(self):
        graph = SimpleNamespace(search=AsyncMock(return_value=[]))
        with patch.object(flow, "AsyncOpenAI") as sdk:
            result = asyncio.run(flow.answer_with_memory(
                partial(searching_graphiti.search_many, graph, 1), "처음 보는 사람", "family_history",
            ))
        sdk.assert_not_called()
        self.assertEqual(result["memories"], [])
        self.assertIn("찾지 못했어요", result["text"])

    def test_three_way_searches_concurrently_and_returns_every_call_output(self):
        calls = [SimpleNamespace(type="function_call", name="search_family_memory", call_id=str(i),
                                 arguments=json.dumps({"query": q})) for i, q in enumerate(["부모", "반려견"])]
        first = SimpleNamespace(status="completed", output=calls, output_text="")
        final = SimpleNamespace(status="completed", output_text="가족 기록을 확인했어요.")

        async def run():
            started = []
            both_started = asyncio.Event()

            async def search(*, query, group_ids, num_results):
                started.append(query)
                if len(started) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=1)
                return [SimpleNamespace(uuid="shared", group_id="family_1", fact="공통 근거",
                                        valid_at=None, invalid_at=None, episodes=[])]

            graph = SimpleNamespace(search=AsyncMock(side_effect=search))
            with patch.object(flow, "AsyncOpenAI") as sdk:
                client = sdk.return_value.__aenter__.return_value
                client.responses.create = AsyncMock(side_effect=[first, final])
                result = await flow.answer_with_memory(
                    partial(searching_graphiti.search_many, graph, 1), "가족 소식", "stt_correction",
                    images=[SimpleUploadedFile("photo.jpg", b"photo")],
                )
                inputs = client.responses.create.call_args.kwargs["input"]
                outputs = [item for item in inputs if isinstance(item, dict) and item.get("type") == "function_call_output"]
                self.assertEqual([item["call_id"] for item in outputs], ["0", "1"])
                self.assertEqual(len(result["memories"]), 1)
                self.assertEqual(result["queries"], ["부모", "반려견"])
                self.assertTrue(all(call.kwargs["instructions"].startswith(provider.FEATURE_INSTRUCTIONS["stt_correction"])
                                    for call in client.responses.create.await_args_list))
                self.assertEqual(inputs[0]["content"][1]["image_url"], "data:image/jpeg;base64,cGhvdG8=")

        asyncio.run(run())

    def test_flow_failure_keeps_prepared_client_until_shutdown(self):
        with patch.object(flow, "answer_with_memory", new=AsyncMock(side_effect=RuntimeError)), \
             patch.object(graphiti_client, "create_graphiti", return_value="graph") as create, \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as close, \
             searching_workers.SearchPool(1) as pool:
            with self.assertRaises(RuntimeError):
                pool.submit("family_history", 1, "질문").result(timeout=3)
            create.assert_called_once()
            close.assert_not_awaited()
        close.assert_awaited_once_with("graph")

    def test_failed_parallel_query_cancels_other_work_before_worker_reuse(self):
        async def run():
            started = asyncio.Event()
            cancelled = asyncio.Event()

            async def search(*, query, group_ids, num_results):
                if query == "실패":
                    await started.wait()
                    raise RuntimeError("offline")
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

            graph = SimpleNamespace(search=AsyncMock(side_effect=search))
            with self.assertRaises(ExceptionGroup):
                await searching_graphiti.search_many(graph, 1, ["실패", "대기"])
            self.assertTrue(cancelled.is_set())

        asyncio.run(run())

    def test_three_way_can_answer_current_input_without_search(self):
        response = SimpleNamespace(status="completed", output=[], output_text="현재 입력만으로 답했어요.")
        for feature, instruction in provider.FEATURE_INSTRUCTIONS.items():
            if feature in {"post_summary", "post_qa", "digest"}:
                continue  # Post flows are covered in test_post_qa.py; digest never searches.
            with self.subTest(feature=feature), patch.object(flow, "AsyncOpenAI") as sdk:
                search = AsyncMock()
                client = sdk.return_value.__aenter__.return_value
                client.responses.create = AsyncMock(return_value=response)
                result = asyncio.run(flow.answer_with_memory(search, "현재 입력", feature))
                search.assert_not_awaited()
                client.responses.create.assert_awaited_once()
                self.assertEqual(client.responses.create.call_args.kwargs["tool_choice"], "auto")
                self.assertTrue(client.responses.create.call_args.kwargs["instructions"].startswith(instruction))
                self.assertIsNone(result["query"])

    @override_settings(QUERY_AI_MODEL="query-model", QUERY_AI_SERVICE_TIER="", QUERY_AI_REASONING_EFFORT="",
                       STT_AI_MODEL="stt-model", STT_AI_SERVICE_TIER="flex", STT_AI_REASONING_EFFORT="low")
    def test_stt_search_decision_and_answer_use_their_own_model_groups(self):
        reasoning = SimpleNamespace(type="reasoning", id="rs_1")
        call = SimpleNamespace(type="function_call", name="search_family_memory", call_id="0",
                               arguments=json.dumps({"query": "부모"}))
        first = SimpleNamespace(status="completed", output=[reasoning, call], output_text="")
        final = SimpleNamespace(status="completed", output_text="가족 기록을 확인했어요.")
        with patch.object(flow, "AsyncOpenAI") as sdk:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(side_effect=[first, final])
            asyncio.run(flow.answer_with_memory(AsyncMock(return_value=[{"memories": []}]), "입력", "stt_correction"))
        decision, answer = [call.kwargs for call in client.responses.create.await_args_list]
        # Blank QUERY options are not sent.
        self.assertEqual(decision["model"], "query-model")
        self.assertNotIn("service_tier", decision)
        self.assertNotIn("reasoning", decision)
        self.assertEqual((answer["model"], answer["service_tier"], answer["reasoning"]),
                         ("stt-model", "flex", {"effort": "low"}))
        # Reasoning items belong to the query model, so they are not passed to another model.
        self.assertNotIn(reasoning, answer["input"])
        self.assertIn(call, answer["input"])

    @override_settings(SUMMARY_AI_MODEL="summary-model", SUMMARY_AI_SERVICE_TIER="fast", SUMMARY_AI_REASONING_EFFORT="none")
    def test_digest_answers_directly_without_search(self):
        response = SimpleNamespace(status="completed", output=[], output_text="오늘의 가족 소식이에요.")
        search = AsyncMock()
        with patch.object(flow, "AsyncOpenAI") as sdk:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=response)
            result = asyncio.run(flow.answer_with_memory(search, "게시물 목록", "digest"))
        search.assert_not_awaited()
        request = client.responses.create.await_args.kwargs
        self.assertNotIn("tools", request)
        self.assertEqual(request["instructions"], prompts.DIGEST)
        self.assertEqual((request["model"], request["service_tier"], request["reasoning"]),
                         ("summary-model", "fast", {"effort": "none"}))
        self.assertEqual((result["text"], result["query"], result["memories"]), (response.output_text, None, []))

    @override_settings(ANSWER_AI_MODEL="answer-model", ANSWER_AI_SERVICE_TIER="fast", ANSWER_AI_REASONING_EFFORT="none")
    def test_family_history_answers_with_the_answer_group(self):
        edge = SimpleNamespace(uuid="fact", group_id="family_1", fact="준하의 부모는 수진과 도윤",
                               valid_at=None, invalid_at=None, episodes=[])
        graph = SimpleNamespace(search=AsyncMock(return_value=[edge]),
                                driver=SimpleNamespace(execute_query=AsyncMock(return_value=([], None, None))))
        response = SimpleNamespace(status="completed", output_text="수진과 도윤이에요.")
        with patch.object(flow, "AsyncOpenAI") as sdk:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=response)
            asyncio.run(flow.answer_with_memory(
                partial(searching_graphiti.search_many, graph, 1), "준하의 부모", "family_history"))
        request = client.responses.create.call_args.kwargs
        self.assertEqual((request["model"], request["service_tier"], request["reasoning"]),
                         ("answer-model", "fast", {"effort": "none"}))

    def test_unknown_feature_fails_before_search_or_llm(self):
        search = AsyncMock()
        with patch.object(flow, "AsyncOpenAI") as sdk, self.assertRaisesMessage(ValueError, "지원하지 않는"):
            asyncio.run(flow.answer_with_memory(search, "입력", "unknown"))
        search.assert_not_awaited()
        sdk.assert_not_called()


@skipUnless(os.getenv("LIVE_GRAPHITI_TESTS") == "1", "LIVE_GRAPHITI_TESTS=1일 때만 로컬 DB를 검색합니다.")
class LiveHistoryTests(FamilyFixture, TestCase):
    def test_live_seeded_family_history(self):
        # SQLite fixtures are temporary; the existing graph is only searched.
        demo = FamilyRoom.objects.create(pk=900040, owner=self.user, name="샘플 가족", invite_code="LIVE01", password_hash="hashed")
        Membership.objects.filter(user=self.user).delete()
        add_member(demo, self.user)
        cases = json.loads((settings.BASE_DIR / "developer/samples/graph_history_questions.json").read_text(encoding="utf-8"))
        report_dir = settings.BASE_DIR / "developer/test_media"
        report_dir.mkdir(parents=True, exist_ok=True)
        saved_file = report_dir / "history_search_results.json"
        previous = json.loads(saved_file.read_text(encoding="utf-8"))["results"] if saved_file.exists() else []
        previous = {row["question"]: row for row in previous}
        report = {"family_id": demo.pk, "model": settings.ANSWER_AI_MODEL,
                  "run_at": timezone.localtime().isoformat(), "method": "2-way", "results": []}
        original_answer = flow.answer_with_memory

        def spent(seconds):
            return f"{seconds:.3f}초" if seconds is not None else "미측정"

        def summary_stages(row):
            phase = row["timings"]
            searched = row["searched"]
            return (
                f"LLM 판단 {spent(phase['decision'])} | "
                f"검색 {spent(phase['search']) if searched else '생략'} | "
                f"LLM 답변 {spent(phase['answer']) if searched else '생략(판단 단계에서 완료)'} | "
                f"기타 {spent(phase['other'])} | 전체 {spent(phase['total'])}"
            )

        def measure(call):
            phases = {}
            details = {}

            async def timed_answer(search, text, feature, **kwargs):
                kwargs["timings"] = phases
                details.update(await original_answer(search, text, feature, **kwargs))
                return details

            with patch.object(flow, "answer_with_memory", new=timed_answer):
                started = perf_counter()
                output = call()
                elapsed = perf_counter() - started
            timings = {key: round(phases[key], 3) if key in phases else None
                       for key in ("decision", "search", "answer")}
            timings["other"] = round(max(0.0, elapsed - sum(phases.values())), 3) if phases else None
            timings["total"] = round(elapsed, 3)
            return output, details, timings

        for case in cases:
            response, _, timings = measure(
                lambda: self.post("/api/searching/history/", {"question": case["question"]})
            )
            result = {**case, "status": response.status_code, "seconds": timings["total"],
                      **response.json(), "timings": timings}
            if case["question"] in previous:
                old = previous[case["question"]]
                result["previous_text"] = old.get("previous_text", old.get("text"))
            result["missing_expected_terms"] = [term for term in case["expected_terms"] if term not in result.get("text", "")]
            report["results"].append(result)
            saved_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            lines = [f"가족 이력 검색: {report['run_at']}\n모델: {report['model']}\n"]
            for i, row in enumerate(report["results"], 1):
                phase = row["timings"]
                answer_time = spent(phase["answer"]) if row.get("memories") else "생략"
                lines.append(
                    f"{i}. 질문: {row['question']}\n답변: {row.get('text', row.get('error'))}\n"
                    f"응답: {row['status']} / {row['seconds']}초\n"
                    f"단계: LLM 판단 생략(2-way) | 검색 {spent(phase['search'])} | "
                    f"LLM 답변 {answer_time} | 기타 {spent(phase['other'])}\n"
                )
            completed = [row for row in report["results"] if row["status"] == 200
                         and row.get("memories") and all(
                             row["timings"][key] is not None for key in ("search", "answer", "other")
                         )]
            if completed:
                lines.append(
                    f"평균 ({len(completed)}개): 검색 "
                    f"{mean(row['timings']['search'] for row in completed):.3f}초 | "
                    f"LLM 답변 {mean(row['timings']['answer'] for row in completed):.3f}초 | "
                    f"기타 {mean(row['timings']['other'] for row in completed):.3f}초 | "
                    f"전체 {mean(row['seconds'] for row in completed):.3f}초"
                )
            (report_dir / "history_search_results.txt").write_text("\n".join(lines), encoding="utf-8")
            print(f"[{len(report['results'])}/{len(cases)}] {case['question']} → {result.get('text', result.get('error'))}", flush=True)
            print(f"판단 생략 | 검색 {spent(timings['search'])} | "
                  f"답변 {spent(timings['answer']) if result.get('memories') else '생략'} | "
                  f"기타 {spent(timings['other'])} | 전체 {result['seconds']:.3f}초", flush=True)
        # These unsaved captions reuse the existing graph without adding episodes.
        summary_cases = [
            {"author": "지민", "relation": "손녀", "caption": "오늘 민수가 예전에 추천해 준 그 카페에 다시 다녀왔어요. 레몬에이드를 마셨어요.",
             "history_hint": "민수가 추천한 성수동 카페 하루"},
            {"author": "준하", "relation": "손자", "caption": "오늘 영수 할아버지께 배운 방법으로 콩이 사진을 다시 찍었어요.",
             "history_hint": "영수가 가르쳐 준 카메라 초점 맞추기"},
            {"author": "지민", "relation": "손녀", "caption": "오늘 초록이 잎을 따서 엄마 수진이 만든 파스타에 올렸어요.",
             "history_hint": "초록이는 선희가 준 바질 화분"},
        ]
        summary_report = {"family_id": demo.pk, "model": settings.SUMMARY_AI_MODEL,
                          "run_at": timezone.localtime().isoformat(), "method": "3-way", "results": []}
        for case in summary_cases:
            content = json.dumps({"작성자": case["author"], "관계": case["relation"], "원문": case["caption"]},
                                 ensure_ascii=False)
            answer, details, timings = measure(
                lambda: provider.answer_with_memory("post_summary", demo.pk, content)
            )
            searched = details["query"] is not None
            result = {**case, "text": answer, "searched": searched,
                      "queries": details.get("queries", []), "memories": details["memories"], "timings": timings}
            summary_report["results"].append(result)
            (report_dir / "post_summary_results.json").write_text(
                json.dumps(summary_report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            lines = [f"과거 기록을 활용한 게시글 요약: {summary_report['run_at']}\n"
                     f"모델: {summary_report['model']}\n검색이 없으면 판단 단계에서 요약이 완료된 것입니다.\n"]
            for i, row in enumerate(summary_report["results"], 1):
                lines.append(
                    f"{i}. 작성자: {row['author']} ({row['relation']})\n원문: {row['caption']}\n"
                    f"확인할 과거 맥락: {row['history_hint']}\n요약: {row['text']}\n"
                    f"검색어: {', '.join(row['queries']) if row['searched'] else '없음'}\n"
                    f"단계: {summary_stages(row)}\n"
                )
            rows = summary_report["results"]
            searched_rows = [row for row in rows if row["searched"]]
            lines.append(
                f"평균 ({len(rows)}개): LLM 판단 {mean(row['timings']['decision'] for row in rows):.3f}초 | "
                f"기타 {mean(row['timings']['other'] for row in rows):.3f}초 | "
                f"전체 {mean(row['timings']['total'] for row in rows):.3f}초"
            )
            if searched_rows:
                lines.append(
                    f"검색 실행 평균 ({len(searched_rows)}개): "
                    f"검색 {mean(row['timings']['search'] for row in searched_rows):.3f}초 | "
                    f"LLM 답변 {mean(row['timings']['answer'] for row in searched_rows):.3f}초"
                )
            else:
                lines.append("검색 실행: 0개")
            (report_dir / "post_summary_results.txt").write_text("\n".join(lines), encoding="utf-8")
            print(f"[3-way {len(rows)}/{len(summary_cases)}] {case['caption']} → {answer}", flush=True)
            print(summary_stages(result), flush=True)
        self.assertTrue(all(row["status"] == 200 and row.get("text") for row in report["results"]))
        self.assertIn("수진", report["results"][0]["text"])
        self.assertIn("도윤", report["results"][0]["text"])
