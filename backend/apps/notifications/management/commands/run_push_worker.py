import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.notifications.services import dispatch_pending, firebase_send, queue_reminders


class Command(BaseCommand):
    help = "Deliver queued Firebase pushes and queue unanswered questions at 20:00 Asia/Seoul."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        import firebase_admin
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(options={"httpTimeout": 20})
        self.stdout.write("Push worker started (20:00 Asia/Seoul reminders).")
        try:
            while True:
                close_old_connections()
                try:
                    queue_reminders()
                    dispatch_pending(firebase_send)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Push worker iteration failed")
                    if options["once"]:
                        raise
                if options["once"]:
                    return
                time.sleep(10)
        except KeyboardInterrupt:
            self.stdout.write("Push worker stopped.")
