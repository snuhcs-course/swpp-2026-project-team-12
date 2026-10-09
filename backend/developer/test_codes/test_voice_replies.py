import io
import json
import tempfile
import wave
from datetime import datetime, time, timedelta
from html import escape
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import AccessToken, User
from apps.digests.models import Digest
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import Post
from apps.replies.models import Comment, VoiceDraft
from integrations.ai import provider as ai_provider
from integrations.speech import provider as speech_provider

from .test_posts import SAMPLES_DIR, TEST_MEDIA_DIR, sample_image


GRANDMA_REPORT = TEST_MEDIA_DIR / "grandma_report.html"


def wave_audio():
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16000)
        recording.writeframes(b"\x00" * 16000)
    return SimpleUploadedFile("reply.wav", output.getvalue(), content_type="audio/wav")


def sample_reply_audio():
    name = "sample_reply_2.m4a"
    return SimpleUploadedFile(name, (SAMPLES_DIR / name).read_bytes(), content_type="audio/mp4")


class VoiceReplyAPITests(TestCase):
    def setUp(self):
        test_media = Path(settings.BASE_DIR) / "developer" / "test_media"
        test_media.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=test_media)
        self.addCleanup(temporary.cleanup)
        configured = override_settings(MEDIA_ROOT=temporary.name)
        configured.enable()
        self.addCleanup(configured.disable)

        self.owner = User.objects.create_user(
            username="owner", password="Owner-Passphrase1!",
            display_name="정아", gender=User.Gender.FEMALE,
        )
        self.grandma = User.objects.create_user(
            username="paternal_grandma", password="Relative-Passphrase1!",
            display_name="경자", gender=User.Gender.FEMALE,
        )
        self.outsider = User.objects.create_user(
            username="outsider", password="Outsider-Passphrase1!", display_name="외부인"
        )
        room = FamilyRoom.objects.create(
            name="정아네", invite_code="ROOM01", password_hash="hashed", owner=self.owner
        )
        other_room = FamilyRoom.objects.create(
            name="다른 가족", invite_code="ROOM02", password_hash="hashed", owner=self.outsider
        )
        Membership.objects.create(room=room, user=self.owner, slot=Membership.Slot.OWNER)
        Membership.objects.create(room=room, user=self.grandma, slot=Membership.Slot.GRANDMA_FATHER)
        Membership.objects.create(room=other_room, user=self.outsider, slot=Membership.Slot.OWNER)
        self.owner_token = AccessToken.issue(self.owner)
        self.grandma_token = AccessToken.issue(self.grandma)
        self.outsider_token = AccessToken.issue(self.outsider)
        uploaded = self.client.post(
            "/api/posts/",
            {"image": sample_image("sample_img_2.png"), "caption": "논문 너무 어려워 ㅠㅠ"},
            **self.auth(self.owner_token),
        )
        self.assertEqual(uploaded.status_code, 200)
        self.post = Post.objects.get(pk=uploaded.json()["id"])

    @staticmethod
    def auth(token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def json_post(self, path, data, token=None):
        return self.client.post(
            path, json.dumps(data), content_type="application/json",
            **self.auth(token or self.grandma_token),
        )

    def test_stt_review_and_send_creates_one_comment(self):
        transcribe_path = f"/api/posts/{self.post.pk}/replies/transcribe/"
        with patch.object(speech_provider, "transcribe", return_value="정아 고생했다고 전해줘"):
            transcript = self.client.post(
                transcribe_path, {"audio": sample_reply_audio()}, **self.auth(self.grandma_token)
            )
        self.assertEqual(transcript.json(), {"recognized": "정아 고생했다고 전해줘"})
        with patch.object(ai_provider, "rewrite", return_value="정아야, 고생 많았다.") as rewrite:
            prepared = self.json_post(
                f"/api/posts/{self.post.pk}/replies/prepare/", transcript.json()
            )
        self.assertEqual(prepared.status_code, 200)
        rewrite.assert_called_once_with("정아 고생했다고 전해줘", "정아")
        self.assertEqual(prepared.json()["converted"], "정아야, 고생 많았다.")
        self.assertEqual(prepared.json()["author_name"], "정아")
        draft = VoiceDraft.objects.get(pk=prepared.json()["id"])
        self.assertEqual(draft.author, self.grandma)
        self.assertFalse(Comment.objects.exists())

        path = f"/api/replies/{draft.pk}/send/"
        first = self.client.post(path, **self.auth(self.grandma_token))
        second = self.client.post(path, **self.auth(self.grandma_token))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(Comment.objects.count(), 1)
        comment = Comment.objects.get(pk=first.json()["id"])
        self.assertEqual(comment.text, "정아야, 고생 많았다.")
        self.assertEqual(comment.source, "voice")
        self.assertEqual(comment.draft, draft)
        detail = self.client.get(f"/api/posts/{self.post.pk}/", **self.auth(self.owner_token)).json()
        self.assertEqual(detail["comment_count"], 1)
        self.assertEqual(detail["comments"][0]["source"], "voice")
        print("STT, AI review, and idempotent voice reply test pass", flush=True)

    def test_sample_replies_use_text_for_game_and_live_stt_for_paper(self):
        if not settings.ELEVENLABS_API_KEY or not settings.OPENAI_API_KEY:
            self.skipTest("Set ELEVENLABS_API_KEY and OPENAI_API_KEY for live voice replies")

        game_post = self.client.post(
            "/api/posts/",
            {"image": sample_image("sample_img_1.png"),
             "caption": "포챔스에서 독개굴 이로치 잡았다~ 간지 ㅁㅌㅊ?"},
            **self.auth(self.owner_token),
        )
        self.assertEqual(game_post.status_code, 200, game_post.content)
        game_id = game_post.json()["id"]
        text_reply = self.json_post(
            f"/api/posts/{game_id}/comments/", {"text": "정아야, 축하한다! 멋지구나."}
        )
        self.assertEqual(text_reply.status_code, 200, text_reply.content)

        transcript = self.client.post(
            f"/api/posts/{self.post.pk}/replies/transcribe/",
            {"audio": sample_reply_audio()},
            **self.auth(self.grandma_token),
        )
        self.assertEqual(transcript.status_code, 200, transcript.content)
        recognized = transcript.json()["recognized"]
        self.assertTrue(recognized)
        prepared = self.json_post(
            f"/api/posts/{self.post.pk}/replies/prepare/", {"recognized": recognized}
        )
        self.assertEqual(prepared.status_code, 200, prepared.content)
        converted = prepared.json()["converted"]
        self.assertTrue(converted)
        sent = self.client.post(
            f"/api/replies/{prepared.json()['id']}/send/", **self.auth(self.grandma_token)
        )
        self.assertEqual(sent.status_code, 200, sent.content)

        game_comment = Comment.objects.get(pk=text_reply.json()["id"])
        paper_comment = Comment.objects.get(pk=sent.json()["id"])
        self.assertEqual(Comment.objects.count(), 2)
        self.assertEqual((game_comment.post_id, game_comment.source), (game_id, "text"))
        self.assertEqual((paper_comment.post_id, paper_comment.source), (self.post.pk, "voice"))
        self.assertEqual(paper_comment.text, converted)

        summaries = {}
        for post_id in (game_id, self.post.pk):
            message = self.client.get(
                f"/api/posts/{post_id}/message/", **self.auth(self.grandma_token)
            )
            self.assertEqual(message.status_code, 200, message.content)
            self.assertEqual(message.json()["status"], "ready", message.content)
            summaries[post_id] = message.json()["text"]
            self.assertTrue(summaries[post_id].strip())

        digest_date = timezone.localdate() - timedelta(days=1)
        digest_cutoff = timezone.make_aware(datetime.combine(digest_date, time(21)))
        Post.objects.filter(pk=game_id).update(created_at=digest_cutoff - timedelta(minutes=30))
        Post.objects.filter(pk=self.post.pk).update(created_at=digest_cutoff - timedelta(minutes=20))
        self.post.refresh_from_db()
        digest_response = self.client.get(
            f"/api/digests/?date={digest_date.isoformat()}", **self.auth(self.grandma_token)
        )
        self.assertEqual(digest_response.status_code, 200, digest_response.content)
        digest = digest_response.json()
        self.assertEqual(digest["status"], "ready", digest)
        self.assertCountEqual([post["id"] for post in digest["posts"]], [game_id, self.post.pk])
        self.assertTrue(digest["text"].strip())
        saved_digest = Digest.objects.get(room=self.post.room, date=digest_date)
        self.assertEqual(saved_digest.text, digest["text"])
        with patch.object(ai_provider, "summarize") as summarize:
            cached = self.client.get(
                f"/api/digests/?date={digest_date.isoformat()}", **self.auth(self.grandma_token)
            )
        self.assertEqual(cached.json(), digest)
        summarize.assert_not_called()

        entries = (
            ("sample_img_1.png", Post.objects.get(pk=game_id), game_comment, ""),
            ("sample_img_2.png", self.post, paper_comment, recognized),
        )
        cards = []
        rows = []
        for image_name, post, comment, transcript_text in entries:
            transcript_html = (
                f"<h3>STT 인식 결과</h3><p>{escape(transcript_text)}</p>"
                '<audio controls src="../samples/sample_reply_2.m4a"></audio>'
                if transcript_text else ""
            )
            cards.append(
                f'<article><img src="../samples/{escape(image_name, quote=True)}" alt="게시글 사진">'
                f'<div><h2>{escape(post.author.display_name)}의 게시글</h2>'
                f'<p>{escape(post.caption)}</p>'
                f'<h3>경자 관점 요약</h3><p>{escape(summaries[post.pk])}</p>'
                f'{transcript_html}'
                f'<h3>경자의 댓글 ({escape(comment.source)})</h3>'
                f'<p>{escape(comment.text)}</p></div></article>'
            )
            values = (
                post.pk, post.room.name, post.author.display_name, post.caption,
                post.image.name, timezone.localtime(post.created_at).isoformat(timespec="seconds"),
                comment.pk, comment.source,
            )
            rows.append("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in values) + "</tr>")

        GRANDMA_REPORT.write_text(
            '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<title>Grandma post and reply test</title><style>body{font:16px sans-serif;margin:2rem}'
            'article{display:flex;gap:1.5rem;margin:1.5rem 0;padding:1rem;border:1px solid #ccc}'
            'img{max-width:240px;object-fit:contain}audio{display:block;margin-top:1rem}'
            'table{border-collapse:collapse;width:100%;margin-top:1rem}'
            'th,td{border:1px solid #ccc;padding:.5rem;text-align:left;overflow-wrap:anywhere}'
            '.digest{white-space:pre-wrap;border:1px solid #ccc;padding:1rem}'
            '</style></head><body><h1>정아의 게시글, 경자 관점 요약, 댓글</h1>'
            + "".join(cards)
            + f'<section><h2>{digest_date.isoformat()} 가족의 하루 요약</h2>'
            f'<p>포함된 게시글: {escape(entries[0][1].caption)} / {escape(entries[1][1].caption)}</p>'
            f'<p class="digest">{escape(digest["text"])}</p></section>'
            + '<h2>테스트 DB의 게시글·댓글</h2><table><thead><tr>'
            '<th>Post ID</th><th>Room</th><th>Author</th><th>Caption</th>'
            '<th>Image path</th><th>Created at</th><th>Comment ID</th><th>Source</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></body></html>',
            encoding="utf-8",
        )
        print(f"Paper STT recognized: {recognized}", flush=True)
        print(f"Paper voice reply: {paper_comment.text}", flush=True)
        print(f"Game text reply: {game_comment.text}", flush=True)
        print(f"Two-post daily digest: {digest['text']}", flush=True)
        print(f"Grandma report: {GRANDMA_REPORT.relative_to(settings.BASE_DIR.parent).as_posix()}", flush=True)

    @override_settings(ELEVENLABS_API_KEY="test-only", ELEVENLABS_STT_MODEL="scribe_v2")
    def test_stt_provider_request_and_errors(self):
        path = f"/api/posts/{self.post.pk}/replies/transcribe/"
        with patch("urllib.request.urlopen", return_value=io.BytesIO('{"text":"  정아야 고생했다  "}'.encode())) as urlopen:
            response = self.client.post(path, {"audio": wave_audio()}, **self.auth(self.grandma_token))
        self.assertEqual(response.json(), {"recognized": "정아야 고생했다"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.elevenlabs.io/v1/speech-to-text")
        self.assertIn(b'name="model_id"\r\n\r\nscribe_v2', request.data)
        self.assertIn(b'name="language_code"\r\n\r\nkor', request.data)
        self.assertIn(b"RIFF", request.data)
        self.assertNotIn(b"reply.wav", request.data)
        self.assertEqual(request.get_header("Xi-api-key"), "test-only")

        with patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"text":""}')):
            self.assertEqual(self.client.post(
                path, {"audio": wave_audio()}, **self.auth(self.grandma_token)
            ).status_code, 400)
        with override_settings(ELEVENLABS_API_KEY=""):
            self.assertEqual(self.client.post(
                path, {"audio": wave_audio()}, **self.auth(self.grandma_token)
            ).status_code, 503)
        self.assertEqual(self.client.post(
            path, {"audio": SimpleUploadedFile("bad.wav", b"not audio")},
            **self.auth(self.grandma_token),
        ).status_code, 400)
        self.assertEqual(self.client.post(
            path, {"audio": SimpleUploadedFile("big.wav", b"RIFF" + b"x" * (5 * 1024 * 1024))},
            **self.auth(self.grandma_token),
        ).status_code, 400)
        print("STT provider and upload validation test pass", flush=True)

    def test_voice_reply_room_author_and_input_validation(self):
        transcribe_path = f"/api/posts/{self.post.pk}/replies/transcribe/"
        prepare_path = f"/api/posts/{self.post.pk}/replies/prepare/"
        self.assertEqual(self.client.post(transcribe_path).status_code, 401)
        self.assertEqual(self.client.post(
            transcribe_path, {"audio": wave_audio()}, **self.auth(self.outsider_token)
        ).status_code, 404)
        self.assertEqual(self.json_post(
            prepare_path, {"recognized": "안녕"}, self.outsider_token
        ).status_code, 404)
        for recognized in (" ", "가" * 2001, 42):
            self.assertEqual(self.json_post(prepare_path, {"recognized": recognized}).status_code, 400)
        draft = VoiceDraft.objects.create(
            post=self.post, author=self.grandma, recognized="안녕", converted="정아야, 안녕."
        )
        self.assertEqual(self.client.post(
            f"/api/replies/{draft.pk}/send/", **self.auth(self.owner_token)
        ).status_code, 404)
        self.assertEqual(self.client.post(
            "/api/replies/999999/send/", **self.auth(self.grandma_token)
        ).status_code, 404)
        self.assertFalse(Comment.objects.exists())
        print("Voice reply room, author, and input validation test pass", flush=True)

    def test_rewrite_failure_does_not_create_draft(self):
        path = f"/api/posts/{self.post.pk}/replies/prepare/"
        with patch.object(ai_provider, "rewrite", side_effect=ai_provider.AIUnavailable("unavailable")):
            self.assertEqual(self.json_post(path, {"recognized": "안녕"}).status_code, 503)
        self.assertFalse(VoiceDraft.objects.exists())
        self.assertFalse(Comment.objects.exists())
        with patch.object(ai_provider, "generate", return_value="정아야, 고생 많았다.") as generate:
            self.assertEqual(ai_provider.rewrite("정아 고생했다고 전해줘", "정아"), "정아야, 고생 많았다.")
        self.assertIn("전달 요청", generate.call_args.args[0])
        self.assertEqual(json.loads(generate.call_args.args[1]), {
            "게시물 작성자": "정아", "인식된 말": "정아 고생했다고 전해줘"
        })
        print("Voice reply AI rewrite and failure test pass", flush=True)
