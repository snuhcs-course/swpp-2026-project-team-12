import io
import json
import os
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.accounts.models import AccessToken, User
from apps.families.models import FamilyRoom
from apps.posts.models import Post
from integrations.speech import provider, voices

from .test_posts import sample_image

from .family_fixtures import auth_headers, add_member, link_parent, sample_family


TEST_MEDIA_DIR = Path(__file__).resolve().parents[1] / "test_media"


def voice_list(m="", f=""):
    return {"m": {"name": "남성 목소리", "voice_id": m, "description": ""},
            "f": {"name": "여성 목소리", "voice_id": f, "description": ""}}


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
        add_member(self.room, self.owner)
        add_member(self.room, self.member, 2)
        link_parent(self.room, self.member, self.room.owner, generations=2)
        self.owner_token = AccessToken.issue(self.owner)
        self.token = AccessToken.issue(self.member)
        self.outsider_token = AccessToken.issue(self.outsider)

    def speak(self, text, token=None):
        return self.client.post(
            "/api/speech/",
            data=json.dumps({"text": text}),
            content_type="application/json",
            **auth_headers(token or self.token),
        )

    @override_settings(ELEVENLABS_API_KEY="test-only", TTS_DEFAULT_VOICE="m", TTS_VOICES=voice_list(m="test-voice"),
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

    @override_settings(ELEVENLABS_API_KEY="test-only", TTS_DEFAULT_VOICE="m", TTS_VOICES=voice_list(m="voice-m", f="voice-f"))
    def test_speech_uses_the_account_voice_and_caches_each_voice(self):
        with patch("urllib.request.urlopen", return_value=AudioResponse(b"voice-m-mp3")) as urlopen:
            self.assertEqual(self.speak("안녕하세요").content, b"voice-m-mp3")
        self.assertIn("/text-to-speech/voice-m?", urlopen.call_args.args[0].full_url)

        self.member.tts_voice = "f"
        self.member.save(update_fields=["tts_voice"])
        with patch("urllib.request.urlopen", return_value=AudioResponse(b"voice-f-mp3")) as urlopen:
            self.assertEqual(self.speak("안녕하세요").content, b"voice-f-mp3")
        self.assertIn("/text-to-speech/voice-f?", urlopen.call_args.args[0].full_url)
        self.assertEqual(len(list((self.media_root / "speech").glob("*.mp3"))), 2)

        with override_settings(TTS_DEFAULT_VOICE="m", TTS_VOICES=voice_list(m="voice-m")):
            self.assertEqual(self.speak("새 문장").status_code, 503)

    @override_settings(TTS_DEFAULT_VOICE="m", TTS_VOICES={**voice_list(m="voice-m"), "calm": {
        "name": "차분한 목소리", "voice_id": "voice-calm", "description": "느리고 따뜻한 말투"}})
    def test_voice_list_is_public_and_hides_unconfigured_voices(self):
        response = self.client.get("/api/speech/voices/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"default": "m", "voices": [
            {"key": "m", "name": "남성 목소리", "description": "", "sample": False},
            {"key": "calm", "name": "차분한 목소리", "description": "느리고 따뜻한 말투", "sample": False},
        ]})
        self.assertEqual(self.client.post("/api/speech/voices/").status_code, 405)

    @override_settings(TTS_DEFAULT_VOICE="m", TTS_VOICES=voice_list(m="voice-m", f="voice-f"))
    def test_voice_samples_are_public_and_follow_the_voice_id(self):
        sample_dir = self.media_root / "samples"
        sample_dir.mkdir()
        (sample_dir / "voice-m.mp3").write_bytes(b"sample-m")
        with patch("integrations.speech.voices.SAMPLE_DIR", sample_dir):
            listed = self.client.get("/api/speech/voices/").json()["voices"]
            self.assertEqual([(voice["key"], voice["sample"]) for voice in listed], [("m", True), ("f", False)])
            sample = self.client.get("/api/speech/voices/m/sample/")
            self.assertEqual((sample.status_code, sample.content, sample["Content-Type"]), (200, b"sample-m", "audio/mpeg"))
            for key in ("f", "retired"):
                with self.subTest(key=key):
                    self.assertEqual(self.client.get(f"/api/speech/voices/{key}/sample/").status_code, 404)

    @override_settings(ELEVENLABS_API_KEY="test-only", TTS_DEFAULT_VOICE="m", TTS_VOICES=voice_list(m="voice-m"))
    def test_generate_voice_samples_writes_only_missing_samples(self):
        sample_dir = self.media_root / "samples"
        with patch("integrations.speech.voices.SAMPLE_DIR", sample_dir),                 patch("urllib.request.urlopen", return_value=AudioResponse(b"sample-mp3")) as urlopen:
            call_command("generate_voice_samples", stdout=io.StringIO())
            call_command("generate_voice_samples", stdout=io.StringIO())
        self.assertEqual(urlopen.call_count, 1, "An existing sample is kept, and a voice without an ID is skipped")
        request = urlopen.call_args.args[0]
        self.assertIn("/text-to-speech/voice-m?", request.full_url)
        self.assertEqual(json.loads(request.data)["text"], voices.SAMPLE_TEXT)
        self.assertEqual((sample_dir / "voice-m.mp3").read_bytes(), b"sample-mp3")

    def test_default_voice_must_be_a_listed_voice(self):
        with override_settings(TTS_DEFAULT_VOICE="m", TTS_VOICES=voice_list(m="voice-m")):
            self.assertEqual(voices.check_voice_list(None), [])
        with override_settings(TTS_DEFAULT_VOICE="retired", TTS_VOICES=voice_list(m="voice-m")):
            self.assertEqual([error.id for error in voices.check_voice_list(None)], ["speech.E001"])

    @override_settings(ELEVENLABS_API_KEY="test-only", TTS_DEFAULT_VOICE="m", TTS_VOICES=voice_list(m="voice-m"))
    def test_account_with_a_removed_voice_falls_back_to_the_default(self):
        self.member.tts_voice = "retired"
        self.member.save(update_fields=["tts_voice"])
        self.assertEqual(self.client.get("/api/accounts/me/", **auth_headers(self.token)).json()["tts_voice"], "m")
        with patch("urllib.request.urlopen", return_value=AudioResponse(b"voice-m-mp3")) as urlopen:
            self.assertEqual(self.speak("안녕하세요").status_code, 200)
        self.assertIn("/text-to-speech/voice-m?", urlopen.call_args.args[0].full_url)

    def test_grandma_post_summaries_are_spoken_live(self):
        if not settings.ELEVENLABS_API_KEY or not voices.voice_id(""):
            self.skipTest("Set ELEVENLABS_API_KEY and the default voice's voice_id in TTS_VOICES for live TTS")
        use_mock_ai = os.getenv("MOCK_AI_TESTS") == "1"
        if not use_mock_ai and not settings.OPENAI_API_KEY:
            self.skipTest("Set OPENAI_API_KEY for live summaries, or MOCK_AI_TESTS=1")

        sample_family(self.room, self.owner, grandma=self.member)
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
                    **auth_headers(self.owner_token),
                )
                self.assertEqual(uploaded.status_code, 200, uploaded.content)
                post = Post.objects.get(pk=uploaded.json()["id"])
                self.assertEqual(post.author.display_name, "정아")
                self.assertEqual(post.caption, caption)
                message = self.client.get(
                    f"/api/posts/{post.pk}/message/",
                    **auth_headers(self.token),
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
            **auth_headers(self.token),
        ).status_code, 415)
        print("Speech authentication and validation test pass", flush=True)

    @override_settings(ELEVENLABS_API_KEY="test-only", TTS_DEFAULT_VOICE="m", TTS_VOICES=voice_list(m="test-voice"))
    def test_speech_provider_failures_do_not_cache_audio(self):
        with override_settings(TTS_DEFAULT_VOICE="m", TTS_VOICES=voice_list()):
            self.assertEqual(self.speak("안녕하세요").status_code, 503)
        with patch("urllib.request.urlopen", return_value=AudioResponse(b"not-mp3", "text/plain")):
            self.assertEqual(self.speak("안녕하세요").status_code, 503)
        self.assertFalse((self.media_root / "speech").exists())
        print("Speech provider failure test pass", flush=True)
