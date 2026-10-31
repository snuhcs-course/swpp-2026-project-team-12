import io
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import AccessToken, User
from apps.api import APIError
from apps.digests.services import generate_digest
from apps.families.models import FamilyRoom
from apps.posts.models import DailyQuestion, Post, QuestionAnswer, QuestionTemplate
from apps.posts.daily_questions import ROTATION, definition, ensure_today, load_rotation

from .family_fixtures import add_member, auth_headers


class QuestionRotationTests(SimpleTestCase):
    def load_content(self, content):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "questions.json"
            path.write_text(content, encoding="utf-8")
            with patch("apps.posts.daily_questions.ROTATION_PATH", path):
                return load_rotation()

    def test_json_loader_preserves_order_and_validates_question_definitions(self):
        entries = [
            {"kind": "choice", "title": " 함께할 일은? ", "options": [" 산책 ", "요리"]},
            {"kind": "text", "title": "고마웠던 일은?", "options": []},
        ]
        self.assertEqual(self.load_content(json.dumps(entries, ensure_ascii=False)), [
            ("choice", "함께할 일은?", ["산책", "요리"]), ("text", "고마웠던 일은?", []),
        ])

    def test_invalid_json_or_definitions_fail_with_configuration_error(self):
        for content in ("{", "[]", "{}", "[null]", '[{"title": "누락"}]', *[
            json.dumps([entry]) for entry in [
                {"kind": [], "title": "질문", "options": []},
                {"kind": "text", "title": " ", "options": []},
                {"kind": "text", "title": "질문", "options": ["선택지"]},
                {"kind": "choice", "title": "질문", "options": ["중복", "중복"]},
                {"kind": "choice", "title": "질문", "options": ["하나"]},
            ]
        ]):
            with self.subTest(content=content), self.assertRaises(ImproperlyConfigured):
                self.load_content(content)

    def test_missing_json_file_reports_its_path(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "missing.json"
            with patch("apps.posts.daily_questions.ROTATION_PATH", path):
                with self.assertRaises(ImproperlyConfigured) as error:
                    load_rotation()
            self.assertIn(str(path), str(error.exception))


class DailyQuestionConcurrencyTests(SimpleTestCase):
    def test_concurrent_first_feed_and_question_request_on_file_sqlite(self):
        # A separate process keeps the real file-backed SQLite connections
        # independent of Django's shared in-memory test database and transactions.
        with TemporaryDirectory() as folder:
            env = {**os.environ, "DJANGO_DB_PATH": str(Path(folder) / "concurrent.sqlite3"), "PYTHONIOENCODING": "utf-8"}
            result = subprocess.run(
                [sys.executable, "-m", "developer.test_codes.daily_question_concurrency_case"],
                cwd=Path(__file__).resolve().parents[2], env=env,
                capture_output=True, text=True, encoding="utf-8", timeout=45,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DailyQuestionTests(TestCase):
    def setUp(self):
        self.day = date(2026, 10, 31)
        clock = patch("apps.posts.daily_questions.timezone.localdate", return_value=self.day)
        clock.start(); self.addCleanup(clock.stop)
        self.owner = User.objects.create_user(username="daily-owner", display_name="정아")
        self.grandma = User.objects.create_user(username="daily-grandma", display_name="할머니")
        self.outsider = User.objects.create_user(username="daily-other", display_name="다른 가족")
        self.room = FamilyRoom.objects.create(owner=self.owner, name="가족", invite_code="DAILY1", password_hash="unused")
        self.other_room = FamilyRoom.objects.create(owner=self.outsider, name="다른 가족", invite_code="DAILY2", password_hash="unused")
        for room, user in ((self.room, self.owner), (self.room, self.grandma), (self.other_room, self.outsider)):
            add_member(room, user)
        self.auth = auth_headers(AccessToken.issue(self.owner), self.room)
        self.grandma_auth = auth_headers(AccessToken.issue(self.grandma), self.room)
        self.other_auth = auth_headers(AccessToken.issue(self.outsider), self.other_room)

    def today(self, auth=None):
        result = self.client.get("/api/daily-questions/today/", **(auth or self.auth))
        self.assertEqual(result.status_code, 200, result.content)
        return result.json()

    def answer(self, pk, payload, auth=None):
        return self.client.put(f"/api/daily-questions/{pk}/answer/", json.dumps(payload), content_type="application/json", **(auth or self.auth))

    def test_sqlite_lock_retries_are_bounded_and_failed_posts_are_rolled_back(self):
        for code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED_SHAREDCACHE):
            cause = sqlite3.OperationalError("database is locked")
            cause.sqlite_errorcode = code
            error = OperationalError("database is locked")
            error.__cause__ = cause
            with self.subTest(code=code), patch("apps.posts.daily_questions.DailyQuestion.objects.create", side_effect=error) as create, patch("apps.posts.daily_questions.time.sleep") as sleep:
                with self.assertRaises(APIError) as caught:
                    ensure_today(self.room)
                self.assertEqual(caught.exception.status, 503)
                self.assertEqual(create.call_count, 6)
                self.assertEqual(sleep.call_count, 5)
            self.assertFalse(Post.objects.exists())
            self.assertFalse(DailyQuestion.objects.exists())

    def test_non_lock_database_error_is_not_retried(self):
        with patch("apps.posts.daily_questions.Post.objects.create", side_effect=OperationalError("no such table")) as create, patch("apps.posts.daily_questions.time.sleep") as sleep:
            with self.assertRaises(OperationalError):
                ensure_today(self.room)
        create.assert_called_once()
        sleep.assert_not_called()

    def test_json_rotation_cycles_by_date_and_published_questions_stay_frozen(self):
        self.assertEqual(definition(self.day), ("주말에 가족과 시간을 보낸다면?", "choice", ["집에서 쉬기", "밖에서 산책"]))
        self.assertEqual(definition(self.day + timedelta(days=1)), ("어릴 때 가장 좋아했던 놀이는?", "text", []))
        self.assertEqual(definition(self.day + timedelta(days=len(ROTATION))), definition(self.day))
        initial = self.today()
        with patch("apps.posts.daily_questions.ROTATION", [("text", "새 질문", [])]):
            self.assertEqual(self.today(), initial)
            with patch("apps.posts.daily_questions.timezone.localdate", return_value=self.day + timedelta(days=1)):
                self.assertEqual(self.today()["title"], "새 질문")

    def test_daily_entry_survives_new_posts_and_feed_limit_without_duplicate_publication(self):
        initial = self.today()
        Post.objects.bulk_create([Post(room=self.room, author=self.owner, caption=f"소식 {i}") for i in range(105)])
        feed = self.client.get("/api/posts/", **self.auth).json()
        self.assertEqual(len(feed["posts"]), 100)
        self.assertTrue(all(row["kind"] == "news" for row in feed["posts"]))
        self.assertNotIn(initial["post_id"], [row["id"] for row in feed["posts"]])
        self.assertEqual(feed["daily_question"]["id"], initial["id"])
        self.assertEqual(feed["daily_question"]["title"], initial["title"])
        self.assertEqual(self.today()["id"], initial["id"])
        self.assertEqual(DailyQuestion.objects.filter(room=self.room).count(), 1)
        self.assertIsNone(Post.objects.get(pk=initial["post_id"]).author_id)

    def test_other_answers_are_visible_before_participating_and_edit_replaces_own_answer(self):
        question = self.today()
        original = self.answer(question["id"], {"choice": question["options"][0], "text": "같이 영화 볼까요?"}, self.grandma_auth)
        self.assertEqual(original.status_code, 200)
        visible = self.today()
        self.assertEqual(len(visible["answers"]), 1)
        self.assertEqual(visible["answers"][0]["author_id"], self.grandma.pk)
        self.assertNotEqual(question["version"], visible["version"])
        self.assertEqual(self.answer(question["id"], {"choice": question["options"][1]}).status_code, 200)
        edited = self.answer(question["id"], {"choice": question["options"][0], "text": "생각이 바뀌었어요."}).json()
        self.assertEqual(QuestionAnswer.objects.filter(question_id=question["id"]).count(), 2)
        mine = next(row for row in edited["answers"] if row["author_id"] == self.owner.pk)
        self.assertEqual(mine["text"], "생각이 바뀌었어요.")
        self.assertEqual(edited["version"], visible["version"], "Own answers must not create unread activity")

    def test_room_isolation_and_malformed_answers(self):
        question = self.today()
        for path in (f"/api/daily-questions/{question['id']}/",):
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, **self.other_auth).status_code, 404)
        self.assertEqual(self.answer(question["id"], {"choice": question["options"][0]}, self.other_auth).status_code, 404)
        for payload in ({}, {"choice": "없는 선택지"}, {"choice": []}, {"choice": question["options"][0], "text": 1},
                        {"choice": question["options"][0], "text": "가" * 1001}, {"choice": question["options"][0], "source": {}}):
            with self.subTest(payload=str(payload)[:80]):
                self.assertEqual(self.answer(question["id"], payload).status_code, 400)
        self.assertFalse(QuestionAnswer.objects.exists())

    def test_existing_comments_and_voice_input_work_on_system_question(self):
        question = self.today()
        text = "[할머니의 답변]\n같이 산책하고 싶어.\n\n어디로 갈까요?"
        path = f"/api/posts/{question['post_id']}/comments/"
        self.assertEqual(self.client.post(path, json.dumps({"text": text}), content_type="application/json", **self.grandma_auth).status_code, 200)
        updated = self.today()
        self.assertEqual(updated["comments"][0]["text"], text)
        self.assertNotEqual(updated["version"], question["version"])
        voice = self.answer(question["id"], {"choice": question["options"][0], "text": "말로 남긴 이유", "source": "voice"}).json()
        self.assertEqual(voice["answers"][0]["source"], "voice")
        detail = self.client.get(f"/api/posts/{question['post_id']}/", **self.auth).json()
        self.assertEqual(detail["author_name"], "토닥")
        self.assertEqual(self.client.get(f"/api/posts/{question['post_id']}/message/", **self.auth).status_code, 400)

    def test_all_input_kinds_validate_and_past_answers_remain_editable(self):
        for i, (kind, options, good, bad) in enumerate([
            ("text", [], {"text": "고무줄놀이"}, {"text": " "}),
            ("weather", ["맑음", "비"], {"choice": "비", "text": "쉬고 싶어요."}, {"choice": "눈"}),
            ("tier", ["바다", "산"], {"tiers": {"바다": "S", "산": "B"}}, {"tiers": {"바다": "S"}}),
        ]):
            day = self.day - timedelta(days=i + 1)
            post = Post.objects.create(room=self.room, kind="question", caption="지난 질문")
            question = DailyQuestion.objects.create(room=self.room, post=post, date=day, kind=kind, options=options)
            self.assertEqual(self.answer(question.pk, bad).status_code, 400)
            self.assertEqual(self.answer(question.pk, good).status_code, 200)
            self.assertEqual(self.answer(question.pk, good).status_code, 200)
            self.assertEqual(question.answers.count(), 1)
        history = self.client.get("/api/daily-questions/history/", **self.auth).json()
        self.assertEqual(len(history["questions"]), 4)
        other_history = self.client.get("/api/daily-questions/history/", **self.other_auth).json()
        self.assertEqual(len(other_history["questions"]), 1)

    def test_question_only_day_does_not_generate_family_news_digest(self):
        question = ensure_today(self.room)
        noon = timezone.make_aware(datetime.combine(self.day, time(12)))
        Post.objects.filter(pk=question.post_id).update(created_at=noon)
        now = timezone.make_aware(datetime.combine(self.day, time(22)))
        with patch("apps.digests.services.timezone.now", return_value=now), patch("apps.digests.services.provider.summarize") as summarize:
            digest = generate_digest(self.room, self.day)
        self.assertEqual(digest.status, "empty")
        summarize.assert_not_called()

    def test_editorial_question_is_used_and_cannot_change_after_publication(self):
        call_command("publish_daily_question", date=self.day.isoformat(), kind="text", title="오늘 고마웠던 일은?", options=[], stdout=io.StringIO())
        self.assertEqual(self.today()["title"], "오늘 고마웠던 일은?")
        with self.assertRaises(CommandError):
            call_command("publish_daily_question", date=self.day.isoformat(), kind="text", title="바꾼 질문", options=[], stdout=io.StringIO())
        self.assertEqual(QuestionTemplate.objects.get(date=self.day).title, "오늘 고마웠던 일은?")

    def test_other_choice_requires_content_and_edits_without_mixing_the_reason(self):
        question = self.today()
        self.assertEqual(question["options"].count("기타"), 1)
        for content in ("", "  ", "가" * 101, 123):
            self.assertEqual(self.answer(question["id"], {"choice": "기타", "other_text": content}).status_code, 400)
        saved = self.answer(question["id"], {"choice": "기타", "other_text": "  노래 듣기  ", "text": "같이 듣고 싶어요."}).json()
        own = saved["answers"][0]
        self.assertEqual((own["choice"], own["other_text"], own["text"]), ("기타", "노래 듣기", "같이 듣고 싶어요."))
        self.assertEqual(self.today(self.grandma_auth)["answers"][0]["other_text"], "노래 듣기")
        self.assertEqual(self.answer(question["id"], {"choice": "기타", "other_text": "요리"}).status_code, 200)
        self.assertEqual(QuestionAnswer.objects.count(), 1)
        self.assertEqual(self.answer(question["id"], {"choice": question["options"][0], "other_text": "숨긴 내용"}).status_code, 400)
        regular = self.answer(question["id"], {"choice": question["options"][0]}).json()
        self.assertEqual(regular["answers"][0]["other_text"], "")
        self.assertEqual(QuestionAnswer.objects.count(), 1)

    def test_existing_other_option_is_not_duplicated_and_weather_supports_it(self):
        question = self.today()
        record = DailyQuestion.objects.get(pk=question["id"])
        record.kind = "weather"; record.options = ["맑음", "비", "기타"]; record.save()
        self.assertEqual(self.today()["options"], ["맑음", "비", "기타"])
        self.assertEqual(self.answer(record.pk, {"choice": "기타", "other_text": "안개"}).status_code, 200)
