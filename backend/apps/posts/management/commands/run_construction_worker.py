from django.core.management.base import BaseCommand, CommandError

from apps.families.models import FamilyRoom


class Command(BaseCommand):
    help = "한 가족의 가계도와 새 게시물을 Graphiti에 저장합니다."

    def add_arguments(self, parser):
        parser.add_argument("--family-id", type=int, required=True)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        from integrations.ai_workers.construction_workers import run_worker

        if not FamilyRoom.objects.filter(pk=options["family_id"]).exists():
            raise CommandError("존재하는 가족 방 ID를 지정하세요.")
        try:
            run_worker(options["family_id"], options["once"], self.stdout, self.stderr)
        except (ValueError, RuntimeError) as error:
            raise CommandError(str(error)) from error
