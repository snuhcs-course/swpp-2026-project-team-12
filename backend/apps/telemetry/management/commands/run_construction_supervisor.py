from threading import Event
import signal
from django.conf import settings
from django.core.management.base import BaseCommand
from integrations.telemetry import emit


class Command(BaseCommand):
    help = 'Run the existing family construction manager as a separate process.'

    def handle(self, *args, **options):
        from integrations.ai_workers.construction_manager import CONSTRUCTION_MANAGER
        # Only this explicit standalone process owns automatic construction.
        settings.GRAPHITI_AUTO_CONSTRUCTION = True
        stopped = Event()
        previous = {sig: signal.signal(sig, lambda *_: stopped.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
        emit('service_started', component='construction', result='success')
        try:
            CONSTRUCTION_MANAGER.start()
            stopped.wait()
        finally:
            CONSTRUCTION_MANAGER.shutdown()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            emit('service_stopped', component='construction', result='success')
