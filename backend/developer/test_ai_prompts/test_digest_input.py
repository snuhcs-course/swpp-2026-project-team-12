"""Offline regressions for digest photo ownership at the actual SDK boundary."""

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.core.files.base import ContentFile
from django.test import SimpleTestCase
from django.utils import timezone

from integrations.ai import digest_output, flow, provider


class DigestInputTests(SimpleTestCase):
    def post(self, pk, author_id, caption, images=(), name="동명이인"):
        return SimpleNamespace(
            pk=pk, room_id=1, author_id=author_id,
            author=SimpleNamespace(display_name=name), caption=caption,
            created_at=timezone.now(),
            photo_files=lambda: [ContentFile(value, name=f"{pk}-{i}.jpg")
                                 for i, value in enumerate(images)],
        )

    def request(self, posts):
        with patch.object(provider, "answer_with_memory", return_value="요약") as adapter:
            provider.summarize(posts)
        feature, _, text, images = adapter.call_args.args
        author_ids = [author["작성자 ID"] for author in json.loads(text)]
        response = SimpleNamespace(status="completed", output_text=json.dumps({str(pk): "요약" for pk in author_ids}))
        search = AsyncMock()
        with patch.object(flow, "AsyncOpenAI") as sdk:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=response)
            result = asyncio.run(flow.answer_with_memory(search, text, feature, images=images))
        search.assert_not_awaited()
        client.responses.create.assert_awaited_once()
        request = client.responses.create.await_args.kwargs
        self.assertNotIn("tools", request)
        self.assertEqual(request["text"], digest_output.answer_format(author_ids))
        self.assertEqual(result["summaries"], [{"author_id": pk, "text": "요약"} for pk in author_ids])
        return json.loads(text), request["input"][0]["content"]

    def enclosed_photos(self, content):
        """Independently recover image ownership from what the model receives."""
        photos, current = {}, None
        for item in content:
            if item["type"] == "input_image":
                self.assertIsNotNone(current, "An image escaped its post boundary")
                photos[current].append(base64.b64decode(item["image_url"].split(",", 1)[1]))
                continue
            text = json.loads(item["text"])
            if "게시글 시작" in text:
                self.assertIsNone(current)
                current = text["게시글 시작"]
                photos[current] = []
            elif "게시글 끝" in text:
                self.assertEqual(current, text["게시글 끝"])
                current = None
        self.assertIsNone(current)
        return photos

    def test_grouping_keeps_multiple_photos_with_their_post_and_distinguishes_same_names(self):
        # Grouping changes A1, B1, A2 into A1, A2, B1. Original photo offsets must survive.
        authors, content = self.request([
            self.post(10, 1, "게임", [b"game-1", b"game-2"]),
            self.post(20, 2, "논문", [b"paper"]),
            self.post(11, 1, "두 번째 소식", [b"other-game"]),
        ])
        self.assertEqual([a["작성자 ID"] for a in authors], [1, 2])
        self.assertEqual([p["게시글 ID"] for a in authors for p in a["게시글"]], [10, 11, 20])
        self.assertEqual(self.enclosed_photos(content), {
            10: [b"game-1", b"game-2"], 11: [b"other-game"], 20: [b"paper"],
        })

    def test_text_only_and_photo_only_posts_keep_their_boundaries(self):
        _, content = self.request([
            self.post(1, 1, "집에서 쉬었어요"),
            self.post(2, 2, "", [b"paper"]),
            self.post(3, 1, "", [b"game"]),
        ])
        self.assertEqual(self.enclosed_photos(content), {1: [], 3: [b"game"], 2: [b"paper"]})

    def test_image_budget_cannot_shift_photos_to_a_later_post(self):
        authors, content = self.request([
            self.post(1, 1, "첫 글", [b"first"] * 5),
            self.post(2, 2, "다음 글", [b"second"] * 5),
            self.post(3, 1, "사진 한도 이후", [b"third"]),
        ])
        self.assertEqual(self.enclosed_photos(content), {1: [b"first"] * 5, 3: [], 2: [b"second"] * 3})
        omitted = authors[0]["게시글"][1]
        self.assertEqual((omitted["첨부 사진 수"], omitted["전달 사진 번호"]), (1, []))

    def test_eight_post_budget_does_not_attach_a_ninth_posts_photo_elsewhere(self):
        posts = [self.post(i, 1, "글만 있는 소식") for i in range(1, 9)]
        authors, content = self.request(posts + [self.post(9, 1, "아홉 번째", [b"ninth"])])
        self.assertEqual(self.enclosed_photos(content), {i: [] for i in range(1, 10)})
        self.assertEqual(authors[0]["게시글"][-1]["첨부 사진 수"], 1)

    def test_output_preserves_author_order_and_collapses_paragraph_breaks(self):
        self.assertEqual(digest_output.parse_answer('{"2":"독서했어요.","1":"A를 하고,\\n\\nB와 C도 했어요."}', [1, 2]), [
            {"author_id": 1, "text": "A를 하고, B와 C도 했어요."},
            {"author_id": 2, "text": "독서했어요."},
        ])

    def test_output_rejects_missing_extra_or_empty_author_summaries(self):
        for output in ('{}', '{"1":"소식"}', '{"1":"소식","2":""}',
                       '{"1":"소식","2":12}', '{"1":"소식","2":"다른 소식","3":"외부인"}', '[]', 'plain text'):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                digest_output.parse_answer(output, [1, 2])
