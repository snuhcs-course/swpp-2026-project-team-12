"""Offline checks for the feed-description prompt and multimodal request."""

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from integrations.ai import feed_description, prompts


@override_settings(OPENAI_API_KEY="test-key", SUMMARY_AI_MODEL="test-model")
class FeedDescriptionTests(SimpleTestCase):
    def post(self, image=True, photos=None):
        files = photos if photos is not None else ([ContentFile(b"jpeg-bytes", name="photo.jpg")] if image else [])
        return SimpleNamespace(
            author=SimpleNamespace(display_name="정아"),
            caption="다음 주에 그 카페에 갈 예정이에요.",
            created_at=timezone.now(),
            image=files[0] if files else None,
            photo_files=lambda: files,
        )

    def generate(self, post, response):
        with patch.object(feed_description, "AsyncOpenAI") as sdk:
            client = sdk.return_value.__aenter__.return_value
            client.responses.create = AsyncMock(return_value=response)
            result = asyncio.run(feed_description.describe_post(post))
            return result, client.responses.create.await_args.kwargs

    def test_caption_image_and_metadata_are_sent_for_detailed_description(self):
        post = self.post()
        result, request = self.generate(post, SimpleNamespace(status="completed", output_text=" 상세 기록 "))
        self.assertEqual(result, "상세 기록")
        self.assertEqual(request["instructions"], prompts.POST_DESCRIPTION)
        self.assertEqual(request["model"], "test-model")
        self.assertFalse(request["store"])
        content = request["input"][0]["content"]
        self.assertEqual(json.loads(content[0]["text"]), {
            "작성자": "정아", "작성 시각": post.created_at.isoformat(), "원문": post.caption,
        })
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(content[1]["detail"], "high")
        self.assertEqual(base64.b64decode(content[1]["image_url"].split(",", 1)[1]), b"jpeg-bytes")

    def test_text_only_input_is_supported(self):
        _, request = self.generate(self.post(image=False), SimpleNamespace(status="completed", output_text="기록"))
        self.assertEqual(len(request["input"][0]["content"]), 1)

    def test_all_photos_are_sent_in_cover_then_attachment_order(self):
        files = [ContentFile(value, name=f"{index}.jpg")
                 for index, value in enumerate([b"cover", b"second", b"third", b"fourth", b"fifth"])]
        _, request = self.generate(self.post(photos=files), SimpleNamespace(status="completed", output_text="기록"))
        content = request["input"][0]["content"]
        self.assertEqual(len(content), 6)
        self.assertEqual([base64.b64decode(item["image_url"].split(",", 1)[1]) for item in content[1:]],
                         [b"cover", b"second", b"third", b"fourth", b"fifth"])

    def test_empty_or_incomplete_descriptions_are_rejected(self):
        for status, text in [("incomplete", "partial"), ("completed", "  ")]:
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                self.generate(self.post(), SimpleNamespace(status=status, output_text=text))

    @override_settings(OPENAI_API_KEY="")
    def test_missing_key_fails_without_api_call(self):
        with patch.object(feed_description, "AsyncOpenAI") as sdk, self.assertRaises(RuntimeError):
            asyncio.run(feed_description.describe_post(self.post()))
        sdk.assert_not_called()
