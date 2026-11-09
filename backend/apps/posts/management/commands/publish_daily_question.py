from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.api import APIError
from apps.posts.daily_questions import validate_definition
from apps.posts.models import DailyQuestion, QuestionTemplate


class Command(BaseCommand):
    help = "날짜별 오늘의 질문을 예약합니다. 해당 날짜에 가족방마다 한 번 배포됩니다."

    def add_arguments(self, parser):
        parser.add_argument("--date", required=True)
        parser.add_argument("--kind", choices=["choice", "text", "weather", "tier"], required=True)
        parser.add_argument("--title", required=True)
        parser.add_argument("--options", nargs="*", default=[])

    def handle(self, *args, **options):
        try:
            day = date.fromisoformat(options["date"])
            if day.isoformat() != options["date"] or day < timezone.localdate():
                raise ValueError()
            title, kind, choices = validate_definition(options["title"], options["kind"], options["options"])
        except (ValueError, APIError) as error:
            raise CommandError(str(error) or "오늘 이후의 날짜를 YYYY-MM-DD로 지정하세요.") from error
        with transaction.atomic():
            if DailyQuestion.objects.filter(date=day).exists():
                raise CommandError("이미 배포된 질문은 바꿀 수 없어요. 다음 날짜로 예약해 주세요.")
            QuestionTemplate.objects.update_or_create(date=day, defaults={"title": title, "kind": kind, "options": choices})
        self.stdout.write(self.style.SUCCESS(f"{day}: {title}"))
