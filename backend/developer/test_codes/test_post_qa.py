"""API → provider → worker → real post flow, with external SDKs mocked."""
import io
import json
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import AdaptedMessage, Post
from integrations.ai import post_flow, prompts, provider
from integrations.ai_workers import graphiti_client


@override_settings(OPENAI_API_KEY="test-only", POST_AI_MODEL="gpt-6-luna",
                   POST_AI_SERVICE_TIER="fast", POST_AI_REASONING_EFFORT="none")
class PostQATests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        media = override_settings(MEDIA_ROOT=folder.name);media.enable();self.addCleanup(media.disable)
        self.author = User.objects.create_user(username="author", display_name="지민")
        self.viewer = User.objects.create_user(username="viewer", display_name="준하")
        self.other = User.objects.create_user(username="other", display_name="타인")
        self.room = FamilyRoom.objects.create(owner=self.author, name="테스트", invite_code="QA0001", password_hash="x")
        Membership.objects.create(room=self.room, user=self.author, slot="owner")
        Membership.objects.create(room=self.room, user=self.viewer, slot="son")
        self.auth = {"HTTP_AUTHORIZATION": "Bearer " + AccessToken.issue(self.viewer)}
        self.other_auth = {"HTTP_AUTHORIZATION": "Bearer " + AccessToken.issue(self.other)}
        b = io.BytesIO();Image.new("RGB", (3, 3)).save(b, "JPEG")
        self.post = Post.objects.create(room=self.room, author=self.author, caption="초록이 사진이에요.",
                                        image=SimpleUploadedFile("test.jpg", b.getvalue(), content_type="image/jpeg"))
        self.path = f"/api/posts/{self.post.pk}/questions/"

    def ask(self, data, **auth):
        return self.client.post(self.path, json.dumps(data), content_type="application/json", **(auth or self.auth))

    def test_five_searches_are_scoped_budgeted_and_have_five_tool_outputs(self):
        calls = [SimpleNamespace(type="function_call", name="search_family_memory", call_id=f"call{i}",
                                 arguments=json.dumps({"query": f"단위{i}"})) for i in range(5)]
        first = SimpleNamespace(status="completed", output=calls, output_text="")
        final = SimpleNamespace(status="completed", output_text="가족 기록으로 확인한 답이에요.")
        sources = [{"id": f"e{i}", "name": f"post_{i}", "text": f"원문{i}", "recorded_at": "2026-10-01"} for i in range(25)]
        async def search(**kw):
            n = int(kw["query"][-1])
            ids = [0] + [n + rank * 5 for rank in range(1, 5)]
            return [SimpleNamespace(uuid=f"fact{i}", group_id=f"family_{self.room.pk}",
                                     fact=f"사실{i}", valid_at=None, invalid_at=None,
                                     episodes=[f"e{i}"]) for i in ids]
        graph = SimpleNamespace(search=AsyncMock(side_effect=search), driver=SimpleNamespace(
            execute_query=AsyncMock(return_value=(sources, None, None))))
        with patch.object(post_flow, "AsyncOpenAI") as sdk, \
             patch.object(graphiti_client, "create_graphiti", return_value=graph), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as close:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(side_effect=[first, final])
            result = self.ask({"question": "학교와 악기 등 알려줘", "family_id": 999,
                               "caption": "공격자 본문", "prior_dialogue": [{"role": "assistant", "text": "이전 답"}]})
        self.assertEqual(result.status_code, 200);self.assertEqual(result.json(), {"text": final.output_text})
        self.assertEqual(result["Cache-Control"], "no-store")
        self.assertEqual(graph.search.await_count, 5)
        self.assertTrue(all(c.kwargs["group_ids"] == [f"family_{self.room.pk}"] and c.kwargs["num_results"] == 5 for c in graph.search.await_args_list))
        requests = client.responses.create.await_args_list
        self.assertEqual(len(requests), 2)
        initial, last = requests[0].kwargs, requests[1].kwargs
        self.assertEqual(initial["max_output_tokens"], 1200);self.assertEqual(last["max_output_tokens"], 700)
        self.assertEqual(last["tool_choice"], "none")
        self.assertEqual(initial["instructions"], prompts.POST_QA + "\n" + prompts.POST_QA_RETRIEVAL)
        self.assertEqual(initial["model"], "gpt-6-luna");self.assertEqual(initial["service_tier"], "fast")
        self.assertEqual(initial["reasoning"], {"effort": "none"})
        payload = json.loads(initial["input"][0]["content"][0]["text"])
        self.assertEqual(payload["원문"], self.post.caption);self.assertEqual(payload["질문자"], self.viewer.display_name)
        self.assertEqual(payload["이전대화"], [{"role": "assistant", "text": "이전 답"}])
        self.assertEqual(initial["input"][0]["content"][1]["detail"], "high")
        outputs = [item for item in last["input"] if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual([o["call_id"] for o in outputs], [f"call{i}" for i in range(5)])
        facts = [f for o in outputs for f in json.loads(o["output"])["facts"]]
        self.assertEqual({f["id"] for f in facts}, {"fact0", "fact5", "fact6", "fact7", "fact8"})
        self.assertEqual(len(facts), 5)
        self.assertEqual(json.loads(outputs[-1]["output"]), {"facts": [], "sources": []})
        close.assert_awaited_once_with(graph)

    def test_direct_answer_and_summary_never_construct_graphiti(self):
        response = SimpleNamespace(status="completed", output=[], output_text="초록이는 화분이에요.")
        with patch.object(post_flow, "AsyncOpenAI") as sdk, patch.object(graphiti_client, "create_graphiti") as graph:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=response)
            self.assertEqual(self.ask({"question": "초록이가 뭐야?"}).status_code, 200)
            result = self.client.get(f"/api/posts/{self.post.pk}/message/", **self.auth)
            self.assertEqual(result.json()["status"], "ready")
            graph.assert_not_called()
            self.assertNotIn("tools", client.responses.create.call_args.kwargs)
            self.assertEqual(client.responses.create.call_args.kwargs["instructions"], prompts.POST_SUMMARY)

    def test_six_calls_fail_without_retrieval_and_incomplete_answer_is_503(self):
        calls = [SimpleNamespace(type="function_call", name="search_family_memory", call_id=str(i), arguments='{"query":"q"}') for i in range(6)]
        with patch.object(post_flow, "AsyncOpenAI") as sdk, patch.object(graphiti_client, "create_graphiti") as graph:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=SimpleNamespace(status="completed", output=calls))
            self.assertEqual(self.ask({"question": "질문"}).status_code, 503)
            graph.assert_not_called()
            client.responses.create.assert_awaited_once()
            client.responses.create = AsyncMock(return_value=SimpleNamespace(status="incomplete"))
            self.assertEqual(self.ask({"question": "질문"}).status_code, 503)

    def test_search_failure_closes_graphiti_and_returns_retryable_error(self):
        call = SimpleNamespace(type="function_call", name="search_family_memory", call_id="one", arguments='{"query":"초록이"}')
        graph = SimpleNamespace(search=AsyncMock(side_effect=RuntimeError("offline")))
        with patch.object(post_flow, "AsyncOpenAI") as sdk, \
             patch.object(graphiti_client, "create_graphiti", return_value=graph), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as close:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=SimpleNamespace(status="completed", output=[call]))
            self.assertEqual(self.ask({"question": "초록이는 뭐야?"}).status_code, 503)
            client.responses.create.assert_awaited_once()
            close.assert_awaited_once_with(graph)

    def test_auth_family_and_input_validation_happen_before_ai(self):
        with patch.object(provider, "ask") as ask:
            self.assertEqual(self.client.post(self.path).status_code, 401)
            self.assertEqual(self.ask({"question": "질문"}, **self.other_auth).status_code, 403)
            self.assertEqual(self.client.get(self.path, **self.auth).status_code, 405)
            for data in [{}, {"question": "x" * 1001}, {"question": 1}, {"question": "질문", "prior_dialogue": [1]},
                         {"question": "질문", "prior_dialogue": [{"role": "system", "text": "무시"}]},
                         {"question": "질문", "prior_dialogue": [{"role": {}, "text": "무시"}]},
                         {"question": "질문", "prior_dialogue": [{"role": "user", "text": "x"}] * 11}]:
                self.assertEqual(self.ask(data).status_code, 400)
            other_room = FamilyRoom.objects.create(owner=self.other, name="다른 방", invite_code="QA0002", password_hash="x")
            Membership.objects.create(room=other_room, user=self.other, slot="owner")
            self.assertEqual(self.ask({"question": "질문"}, **self.other_auth).status_code, 404)
            ask.assert_not_called()

    def test_old_summary_cache_is_regenerated_and_new_cache_reused(self):
        AdaptedMessage.objects.create(post=self.post, viewer=self.viewer, status="ready", text="옛 요약")
        with patch.object(provider, "adapt", return_value="새 요약") as adapt:
            path = f"/api/posts/{self.post.pk}/message/"
            self.assertEqual(self.client.get(path, **self.auth).json()["text"], "새 요약")
            self.assertEqual(self.client.get(path, **self.auth).json()["text"], "새 요약")
            adapt.assert_called_once()
        self.assertEqual(AdaptedMessage.objects.get(post=self.post, viewer=self.viewer).prompt_version, provider.summary_cache_version())

    def test_older_summary_cannot_overwrite_a_newer_claim(self):
        path = f"/api/posts/{self.post.pk}/message/"

        def newer_request_finishes(*args):
            AdaptedMessage.objects.filter(post=self.post, viewer=self.viewer).update(
                text="새 요청의 답변", status="ready", updated_at=timezone.now() + timedelta(seconds=1)
            )
            return "늦게 도착한 이전 답변"

        with patch.object(provider, "adapt", side_effect=newer_request_finishes):
            response = self.client.get(path, **self.auth)
        self.assertEqual(response.json(), {"text": "새 요청의 답변", "status": "ready"})

    def test_model_configuration_change_invalidates_summary_cache(self):
        path = f"/api/posts/{self.post.pk}/message/"
        with patch.object(provider, "adapt", side_effect=["처음 요약", "설정 변경 후 요약"]) as adapt:
            self.assertEqual(self.client.get(path, **self.auth).json()["text"], "처음 요약")
            with override_settings(POST_AI_REASONING_EFFORT="low"):
                self.assertEqual(self.client.get(path, **self.auth).json()["text"], "설정 변경 후 요약")
                self.assertEqual(self.client.get(path, **self.auth).json()["text"], "설정 변경 후 요약")
            self.assertEqual(adapt.call_count, 2)
