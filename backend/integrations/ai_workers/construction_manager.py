"""Supervise one local construction thread per committed family room."""

import atexit
import logging
from threading import Event, Lock, Thread

from django.conf import settings
from django.db import close_old_connections, connections

from apps.families.models import FamilyRoom

from .construction_workers import WorkerAlreadyRunning, run_worker


logger = logging.getLogger(__name__)


class LogOutput:
    def __init__(self, level):
        self.level = level

    def write(self, message):
        if message.strip():
            logger.log(self.level, "%s", message.rstrip())

    def flush(self):
        pass


class ConstructionManager:
    def __init__(self, interval=5):
        self.interval = interval
        self._lock = Lock()
        self._wake = Event()
        self._stop = Event()
        self._thread = None
        self._workers = {}

    def start(self):
        # WSGI/ASGI startup calls this, never AppConfig.ready() or a signal.
        if not settings.GRAPHITI_AUTO_CONSTRUCTION:
            return self
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("Cannot start construction after shutdown")
            if self._thread is None:
                self._thread = Thread(target=self._supervise, name="graphiti-construction", daemon=True)
                self._thread.start()
        return self

    def wake(self):
        # Safe in a request's on_commit callback; no SQL, network I/O or waiting.
        self._wake.set()

    def _supervise(self):
        try:
            while not self._stop.is_set():
                self._wake.clear()
                try:
                    self._reconcile()
                except Exception:
                    logger.exception("Could not discover family construction workers; retrying")
                # Also recovers missed signals, other server processes and failed workers.
                self._wake.wait(self.interval)
        finally:
            connections.close_all()

    def _reconcile(self):
        close_old_connections()
        family_ids = set(FamilyRoom.objects.values_list("pk", flat=True))
        with self._lock:
            if self._stop.is_set():
                return
            for family_id, (thread, stop) in list(self._workers.items()):
                if family_id not in family_ids:
                    stop.set()
                if not thread.is_alive():
                    del self._workers[family_id]
            for family_id in sorted(family_ids - self._workers.keys()):
                stop = Event()
                thread = Thread(target=self._run_family, args=(family_id, stop),
                                name=f"graphiti-construction-{family_id}", daemon=True)
                self._workers[family_id] = (thread, stop)
                thread.start()

    def _run_family(self, family_id, stop):
        try:
            run_worker(family_id, False, LogOutput(logging.INFO), LogOutput(logging.ERROR),
                       stop_event=stop)
        except WorkerAlreadyRunning:
            # A manual worker or another web process owns the shared family lock.
            logger.debug("Construction for family %s is owned by another process", family_id)
        except Exception:
            logger.exception("Construction worker for family %s stopped; retrying", family_id)
        finally:
            connections.close_all()

    def shutdown(self, wait=True):
        with self._lock:
            self._stop.set()
            self._wake.set()
            for _, stop in self._workers.values():
                stop.set()
            supervisor = self._thread
            workers = [thread for thread, _ in self._workers.values()]
        if wait:
            if supervisor is not None:
                supervisor.join()
            for thread in workers:
                thread.join()


CONSTRUCTION_MANAGER = ConstructionManager()
atexit.register(CONSTRUCTION_MANAGER.shutdown)
