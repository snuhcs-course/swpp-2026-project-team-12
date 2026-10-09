import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.families.models import FamilyRoom
from apps.digests.services import generate_digest


class Command(BaseCommand):
    help = "Generate each room's daily digest at its configured Korean time."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        while True:
            now = timezone.localtime()
            for room in FamilyRoom.objects.all():
                chosen = now.date() if now.time() >= room.digest_time else now.date() - timedelta(days=1)
                generate_digest(room, chosen)
            if options["once"]:
                return
            time.sleep(30)
