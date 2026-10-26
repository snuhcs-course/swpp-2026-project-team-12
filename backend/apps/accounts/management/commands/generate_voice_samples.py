from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from integrations.speech import provider, voices


class Command(BaseCommand):
    help = "Generate the missing preview sample of each TTS voice in settings.TTS_VOICES."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Regenerate samples that already exist.")

    def handle(self, *args, **options):
        failed = []
        for key, voice in settings.TTS_VOICES.items():
            voice_id = voice.get("voice_id")
            if not voice_id:
                self.stdout.write(f"{key}: skipped, no voice_id")
                continue
            path = voices.SAMPLE_DIR / (voice_id + ".mp3")
            if path.exists() and not options["force"]:
                self.stdout.write(f"{key}: kept {path.name}")
                continue
            try:
                provider.write_atomically(path, provider.render(voices.SAMPLE_TEXT, voice_id))
            except provider.SpeechUnavailable as error:
                failed.append(key)
                self.stderr.write(f"{key}: failed, {error}")
                continue
            self.stdout.write(self.style.SUCCESS(f"{key}: wrote {path.name}"))
        if failed:
            raise CommandError("Could not generate samples for: " + ", ".join(failed))
