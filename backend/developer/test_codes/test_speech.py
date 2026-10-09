import io
import json
import os
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom, Membership
from apps.posts.models import Post
from integrations.speech import provider

from .test_posts import sample_image


TEST_MEDIA_DIR = Path(__file__).resolve().parents[1] / "test_media"


class AudioResponse(io.BytesIO):
    def __init__(self, audio, content_type="audio/mpeg"):
        super().__init__(audio)
        self.headers = {"Content-Type": content_type}


class SpeechAPITests(TestCase):
    def setUp(self):
        TEST_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=TEST_MEDIA_DIR)
        self.addCleanup(temporary.cleanup)
        configured = override_settings(MEDIA_ROOT=temporary.name)
        configured.enable()
        self.addCleanup(configured.disable)
        self.media_root = Path(temporary.name)

        self.owner = User.objects.create_user(
            username="owner", password="Owner-Passphrase1!",
            display_name="정아", gender=User.Gender.FEMALE,
        )
        self.member = User.objects.create_user(
            username="paternal_grandma", password="Relative-Passphrase1!",
            display_name="경자", gender=User.Gender.FEMALE,
        )
        self.outsider = User.objects.create_user(
            username="speech-outsider", password="Speech-Passphrase2!", display_name="외부인"
        )
        self.room = FamilyRoom.objects.create(
            name="정아네", invite_code="ROOM01", password_hash="hashed", owner=self.owner
        )
        Membership.objects.create(room=self.room, user=self.owner, slot=Membership.Slot.OWNER)
        Membership.objects.create(room=self.room, user=self.member, slot=Membership.Slot.GRANDMA_FATHER)
        self.owner_token = AccessToken.issue(self.owner)
        self.token = AccessToken.issue(self.member)
        self.outsider_token = AccessToken.issue(self.outsider)

    def speak(self, text, token=None):
        return self.client.post(
            "/api/speech/",
            data=json.dumps({"text": text}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token or self.token}",
        )

    @override_settings(ELEVENLABS_API_KEY="test-only", ELEVENLABS_VOICE_ID="test-voice",
                       ELEVENLABS_TTS_MODEL="eleven_multilingual_v2")
    def test_speech_request_and_room_cache(self):
        with patch("urllib.request.urlopen", return_value=AudioResponse(b"mp3-data")) as urlopen:
            response = self.speak("  정아가 사진을 올렸어요.  ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"mp3-data")
        self.assertEqual(response["Content-Type"], "audio/mpeg")
        self.assertEqual(response["Cache-Control"], "no-store")
        request = urlopen.call_args.args[0]
        self.assertIn("/text-to-speech/test-voice?output_format=mp3_44100_128", request.full_url)
        self.assertEqual(json.loads(request.data)["text"], "정아가 사진을 올렸어요.")
        self.assertEqual(json.loads(request.data)["voice_settings"]["speed"], 0.85)
        self.assertEqual(request.get_header("Xi-api-key"), "test-only")
        self.assertEqual(len(list((self.media_root / "speech").glob("*.mp3"))), 1)

        with override_settings(ELEVENLABS_API_KEY=""), patch("urllib.request.urlopen") as urlopen:
            cached = self.speak("정아가 사진을 올렸어요.")
            urlopen.assert_not_called()
        self.assertEqual(cached.content, b"mp3-data")

        other_room = FamilyRoom.objects.create(
            name="다른 가족", invite_code="ROOM02", password_hash="hashed", owner=self.outsider
        )
        with patch("urllib.request.urlopen", return_value=AudioResponse(b"other-room")) as urlopen:
            self.assertEqual(provider.synthesize("정아가 사진을 올렸어요.", other_room.pk), b"other-room")
            urlopen.assert_called_once()
        self.assertEqual(len(list((self.media_root / "speech").glob("*.mp3"))), 2)
        print("Speech generation and room cache test pass", flush=True)

    def test_grandma_post_summaries_are_spoken_live(self):
        if not settings.ELEVENLABS_API_KEY or not settings.ELEVENLABS_VOICE_ID:
            self.skipTest("Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID for live TTS")
        use_mock_ai = os.getenv("MOCK_AI_TESTS") == "1"
        if not use_mock_ai and not settings.OPENAI_API_KEY:
            self.skipTest("Set OPENAI_API_KEY for live summaries, or MOCK_AI_TESTS=1")

        for username, name, gender, slot in (
            ("maternal_grandma", "선희", User.Gender.FEMALE, Membership.Slot.GRANDMA_MOTHER),
            ("father", "병호", User.Gender.MALE, Membership.Slot.FATHER),
            ("mother", "지현", User.Gender.FEMALE, Membership.Slot.MOTHER),
            ("son", "준호", User.Gender.MALE, Membership.Slot.SON),
            ("daughter", "수아", User.Gender.FEMALE, Membership.Slot.DAUGHTER),
        ):
            user = User.objects.create_user(
                username=username, password="Relative-Passphrase1!",
                display_name=name, gender=gender,
            )
            Membership.objects.create(room=self.room, user=user, slot=slot)
        self.assertEqual(self.room.members.count(), 7)

        mock_summaries = (
            "손녀 정아가 포챔스에서 색이 다른 독개굴을 잡았다고 해요. 멋진지 가족에게 물어봤어요.",
            "손녀 정아가 논문이 너무 어렵다고 해요. 가족에게 힘든 마음을 전했어요.",
        )
        ai_generation = (
            patch("apps.posts.views.provider.adapt", side_effect=mock_summaries)
            if use_mock_ai else nullcontext()
        )
        with ai_generation:
            for number, (image_name, caption) in enumerate((
                ("sample_img_1.png", "포챔스에서 독개굴 이로치 잡았다~ 간지 ㅁㅌㅊ?"),
                ("sample_img_2.png", "논문 너무 어려워 ㅠㅠ"),
            ), start=1):
                uploaded = self.client.post(
                    "/api/posts/",
                    {"image": sample_image(image_name), "caption": caption},
                    HTTP_AUTHORIZATION=f"Bearer {self.owner_token}",
                )
                self.assertEqual(uploaded.status_code, 200, uploaded.content)
                post = Post.objects.get(pk=uploaded.json()["id"])
                self.assertEqual(post.author.display_name, "정아")
                self.assertEqual(post.caption, caption)
                message = self.client.get(
                    f"/api/posts/{post.pk}/message/",
                    HTTP_AUTHORIZATION=f"Bearer {self.token}",
                )
                self.assertEqual(message.status_code, 200)
                self.assertEqual(message.json()["status"], "ready", message.json())
                summary = message.json()["text"]
                self.assertTrue(summary.strip())

                spoken = self.speak(summary)
                self.assertEqual(spoken.status_code, 200, spoken.content)
                self.assertEqual(spoken["Content-Type"], "audio/mpeg")
                self.assertTrue(spoken.content)
                audio_name = f"grandma_post_{number}_tts.mp3"
                (TEST_MEDIA_DIR / audio_name).write_bytes(spoken.content)
        print("Grandma live TTS test pass: grandma_post_1_tts.mp3, grandma_post_2_tts.mp3", flush=True)

    def test_speech_authentication_and_input_validation(self):
        self.assertEqual(self.client.post("/api/speech/").status_code, 401)
        self.assertEqual(self.speak("안녕하세요", self.outsider_token).status_code, 403)
        self.assertEqual(self.speak("  ").status_code, 400)
        self.assertEqual(self.speak("가" * 4001).status_code, 400)
        self.assertEqual(self.speak(123).status_code, 400)
        self.assertEqual(self.client.post(
            "/api/speech/", data={"text": "안녕하세요"},
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        ).status_code, 415)
        print("Speech authentication and validation test pass", flush=True)

    @override_settings(ELEVENLABS_API_KEY="test-only", ELEVENLABS_VOICE_ID="test-voice")
    def test_speech_provider_failures_do_not_cache_audio(self):
        with override_settings(ELEVENLABS_VOICE_ID=""):
            self.assertEqual(self.speak("안녕하세요").status_code, 503)
        with patch("urllib.request.urlopen", return_value=AudioResponse(b"not-mp3", "text/plain")):
            self.assertEqual(self.speak("안녕하세요").status_code, 503)
        self.assertFalse((self.media_root / "speech").exists())
        print("Speech provider failure test pass", flush=True)
