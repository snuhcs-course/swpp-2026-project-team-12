import asyncio
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase, TestCase

from apps.families.models import FamilyRoom
from apps.posts.models import Post
from apps.searching import services
from integrations.ai import flow, history_evidence

from .family_fixtures import add_member
from .test_searching import FamilyFixture


class HistoryEvidenceAPITests(FamilyFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.first = Post.objects.create(room=self.room, author=self.user, caption="부산 여행", images=["one.jpg", "two.jpg"])
        self.second = Post.objects.create(room=self.room, author=self.user, caption="서울 여행", images=[])
        self.other_room = FamilyRoom.objects.create(owner=self.user, name="다른 가족", invite_code="OTHER", password_hash="hashed")
        add_member(self.other_room, self.user)
        self.foreign = Post.objects.create(room=self.other_room, author=self.user, caption="다른 방의 글", images=[])

    def result(self, sources, citations=None):
        value = {"text": "여행은 부산으로 다녀왔어요.", "memories": [{"sources": sources}, {"sources": sources}]}
        if citations is not None:
            value["source_episode_ids"] = citations
        return value

    def search(self, value):
        with patch.object(services, "search_history", return_value=value):
            response = self.client.post("/api/searching/history/", json.dumps({"question": "여행은 어디로 갔지?"}),
                                        content_type="application/json", **{**self.auth, "HTTP_X_FAMILY_ROOM": str(self.room.pk)})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def source(self, name, id="episode"):
        return {"id": id, "name": name}

    def test_only_cited_current_room_posts_appear_in_citation_order_once(self):
        sources = [self.source(f"post_{self.first.pk}", "first"), self.source(f"post_{self.second.pk}", "second"),
                   self.source(f"post_{self.foreign.pk}", "foreign"), self.source("post_999999", "deleted"),
                   self.source("family_relations_v1", "family")]
        data = self.search(self.result(sources, ["second", "first", "first", "foreign", "deleted", "family", "invented"]))
        self.assertEqual([post["id"] for post in data["evidence_posts"]], [self.second.pk, self.first.pk])
        self.assertEqual(data["evidence_kind"], "cited")
        first = data["evidence_posts"][1]
        self.assertEqual(first["caption"], self.first.caption)
        self.assertEqual(first["author_name"], self.user.display_name)
        self.assertEqual(first["image_count"], 2)
        self.assertEqual([photo["id"] for photo in first["images"]], [0, 1])
        self.assertEqual(first["comment_count"], 0)

    def test_uncited_retrievals_do_not_become_evidence(self):
        sources = [self.source(f"post_{self.first.pk}", "first"), self.source(f"post_{self.second.pk}", "second")]
        data = self.search(self.result(sources, ["second"]))
        self.assertEqual([post["id"] for post in data["evidence_posts"]], [self.second.pk])
        self.assertEqual(self.search(self.result(sources, []))["evidence_posts"], [])

    def test_legacy_worker_sources_remain_supported_and_are_labelled_retrieved(self):
        sources = [self.source(f"post_{self.first.pk}"), self.source(f"post_{self.foreign.pk}", "foreign"),
                   self.source("https://malicious.example/post_2", "url"), self.source("post_01", "leading")]
        data = self.search(self.result(sources))
        self.assertEqual([post["id"] for post in data["evidence_posts"]], [self.first.pk])
        self.assertEqual(data["evidence_kind"], "retrieved")

    def test_removed_post_and_no_retrieval_return_answer_without_fake_cards(self):
        source = self.source(f"post_{self.first.pk}")
        self.first.delete()
        for sources in ([source], []):
            data = self.search(self.result(sources, ["episode"]))
            self.assertEqual(data["evidence_posts"], [])
            self.assertEqual(data["text"], "여행은 부산으로 다녀왔어요.")

    @patch("apps.posts.daily_questions.timezone.localdate", return_value=date(2026, 10, 31))
    def test_daily_question_and_answer_stay_separate_from_memory_evidence(self, _clock):
        from apps.posts.daily_questions import ensure_today

        question = ensure_today(self.room)
        auth = {**self.auth, "HTTP_X_FAMILY_ROOM": str(self.room.pk)}
        feed = self.client.get("/api/posts/", **auth).json()
        self.assertEqual(feed["daily_question"]["id"], question.pk)
        self.assertNotIn(question.post_id, [post["id"] for post in feed["posts"]])
        choice = question.options[0]
        answer = self.client.put(f"/api/daily-questions/{question.pk}/answer/",
                                 json.dumps({"choice": choice, "text": "가족과 함께해요."}),
                                 content_type="application/json", **auth)
        self.assertEqual(answer.status_code, 200)
        sources = [self.source(f"post_{question.post_id}", "question"),
                   self.source(f"post_{self.first.pk}", "news")]
        result = self.search(self.result(sources, ["question", "news"]))
        self.assertEqual([post["id"] for post in result["evidence_posts"]], [self.first.pk])
        self.assertEqual(self.client.get(f"/api/daily-questions/{question.pk}/", **auth)
                         .json()["answers"][0]["text"], "가족과 함께해요.")


class HistoryCitationTests(SimpleTestCase):
    def test_citations_are_deduplicated_and_restricted_to_retrieved_sources(self):
        memories = [{"sources": [{"id": "second"}, {"id": "first"}]}]
        output = json.dumps({"text": "  부산이에요.  ", "source_episode_ids": ["first", "missing", "first", "second"]})
        self.assertEqual(history_evidence.parse_answer(output, memories),
                         {"text": "부산이에요.", "source_episode_ids": ["first", "second"]})

    def test_invalid_answer_or_citation_payload_is_not_shown_as_a_valid_answer(self):
        for output in ("plain text", "[]", '{}', '{"text":"", "source_episode_ids":[]}',
                       '{"text":"답변", "source_episode_ids":"post_1"}', '{"text":"답변", "source_episode_ids":[1]}'):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                history_evidence.parse_answer(output, [])

    def test_history_call_uses_one_structured_answer_and_filters_invented_source_ids(self):
        memories = [{"id": "fact", "fact": "부산 여행", "sources": [{"id": "episode", "name": "post_1"}]}]
        search = AsyncMock(return_value=[{"memories": memories}])
        response = SimpleNamespace(status="completed", output_text=json.dumps({
            "text": "부산으로 다녀왔어요.", "source_episode_ids": ["episode", "invented"]}))
        with patch.object(flow, "AsyncOpenAI") as sdk:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=response)
            result = asyncio.run(flow.answer_with_memory(search, "가족 여행", "family_history"))
        search.assert_awaited_once_with(["가족 여행"])
        client.responses.create.assert_awaited_once()
        self.assertEqual(result["source_episode_ids"], ["episode"])
        self.assertEqual(client.responses.create.await_args.kwargs["text"], history_evidence.ANSWER_FORMAT)
