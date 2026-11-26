"""Automatic construction lifetime and committed-room discovery without live services."""

import asyncio
import io
import tempfile
from contextlib import ExitStack
from queue import Queue
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.db import transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.families import signals
from apps.families.models import FamilyRoom
from apps.families.services import create_room
from apps.posts.models import Post
from integrations.ai_workers import construction_graphiti, construction_manager, construction_workers, graphiti_client
from integrations.ai_workers.construction_manager import ConstructionManager


class ConstructionSignalTests(TransactionTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="construction-owner", display_name="가족")

    def test_room_creation_wakes_only_after_the_whole_transaction_commits(self):
        with patch.object(signals.CONSTRUCTION_MANAGER, "wake") as wake:
            with transaction.atomic():
                room = create_room(self.owner, "가족방", "password", "21:00")
                wake.assert_not_called()
                self.assertEqual(room.members.count(), 1)
            wake.assert_called_once_with()
            wake.reset_mock()
            room.name = "새 이름"
            room.save()
            wake.assert_not_called()

    def test_rolled_back_room_does_not_wake_workers(self):
        with patch.object(signals.CONSTRUCTION_MANAGER, "wake") as wake:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    create_room(self.owner, "취소된 방", "password", "21:00")
                    raise RuntimeError("rollback")
            wake.assert_not_called()
        self.assertFalse(FamilyRoom.objects.exists())

    def test_fixture_loading_does_not_notify_workers(self):
        with patch.object(signals.CONSTRUCTION_MANAGER, "wake") as wake:
            room = FamilyRoom(owner=self.owner, name="fixture", invite_code="FIXTURE", password_hash="hash",
                              created_at=timezone.now())
            room.save_base(raw=True, force_insert=True)
            wake.assert_not_called()


@override_settings(GRAPHITI_AUTO_CONSTRUCTION=True)
class ConstructionManagerTests(TransactionTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="manager-owner", display_name="가족")

    def room(self, code):
        return FamilyRoom.objects.create(owner=self.owner, name=code, invite_code=code, password_hash="hash")

    def manager(self, stack, worker, interval=60):
        manager = ConstructionManager(interval=interval)
        stack.enter_context(patch.object(construction_manager, "run_worker", side_effect=worker))
        stack.enter_context(patch.object(signals, "CONSTRUCTION_MANAGER", manager))
        stack.callback(manager.shutdown)
        return manager

    def test_start_recovers_existing_rooms_and_new_room_signals_do_not_duplicate_workers(self):
        existing = self.room("EXIST")
        started, stopped = Queue(), Queue()

        def worker(family_id, once, stdout, stderr, *, stop_event):
            started.put(family_id)
            stop_event.wait()
            stopped.put(family_id)

        with ExitStack() as stack:
            manager = self.manager(stack, worker)
            manager.start().start()
            self.assertEqual(started.get(timeout=3), existing.pk)
            with transaction.atomic():
                new = self.room("NEW")
                self.assertTrue(started.empty())
            self.assertEqual(started.get(timeout=3), new.pk)
            manager._reconcile()
            self.assertTrue(started.empty())
            self.assertEqual(set(manager._workers), {existing.pk, new.pk})
        self.assertEqual({stopped.get_nowait(), stopped.get_nowait()}, {existing.pk, new.pk})

        # A fresh web process recovers both rooms without another create signal.
        with ExitStack() as stack:
            self.manager(stack, worker).start()
            self.assertEqual({started.get(timeout=3), started.get(timeout=3)}, {existing.pk, new.pk})

    def test_periodic_scan_finds_rooms_without_signals_and_stops_deleted_rooms(self):
        started, stopped = Event(), Event()

        def worker(family_id, once, stdout, stderr, *, stop_event):
            started.set()
            stop_event.wait()
            stopped.set()

        with ExitStack() as stack:
            manager = self.manager(stack, worker, interval=0.02).start()
            # bulk_create deliberately bypasses post_save, like a missed notification.
            room = FamilyRoom(owner=self.owner, name="bulk", invite_code="BULK", password_hash="hash")
            FamilyRoom.objects.bulk_create([room])
            self.assertTrue(started.wait(3))
            room.delete()
            self.assertTrue(stopped.wait(3))

    def test_failed_worker_is_retried_without_stopping_other_families(self):
        first, second = self.room("FIRST"), self.room("SECOND")
        ready, attempts, lock = Queue(), {}, Lock()

        def worker(family_id, once, stdout, stderr, *, stop_event):
            with lock:
                attempts[family_id] = attempts.get(family_id, 0) + 1
                fail = family_id == first.pk and attempts[family_id] == 1
            if fail:
                raise RuntimeError("initialization failed")
            ready.put(family_id)
            stop_event.wait()

        with self.assertLogs(construction_manager.__name__, level="ERROR"), ExitStack() as stack:
            self.manager(stack, worker, interval=0.02).start()
            self.assertEqual({ready.get(timeout=3), ready.get(timeout=3)}, {first.pk, second.pk})
        self.assertEqual(attempts, {first.pk: 2, second.pk: 1})

    def test_discovery_error_is_retried(self):
        recovered = Event()
        manager = ConstructionManager(interval=0.02)
        self.addCleanup(manager.shutdown)

        def discover():
            if not recovered.is_set():
                recovered.set()
                raise RuntimeError("database temporarily unavailable")

        with self.assertLogs(construction_manager.__name__, level="ERROR"), \
             patch.object(manager, "_reconcile", side_effect=discover) as scan:
            manager.start()
            self.assertTrue(recovered.wait(3))
            manager.wake()
            # Synchronize with a successful recovery pass, not a timing-based sleep.
            success = Event()
            scan.side_effect = success.set
            manager.wake()
            self.assertTrue(success.wait(3))
            manager.shutdown()

    def test_family_lock_allows_takeover_after_another_manager_stops(self):
        room = self.room("LOCK")
        started = Queue()

        def construct(family_id, once, stdout, stderr, *, stop_event):
            started.put(family_id)
            stop_event.wait()

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
             patch.object(construction_workers, "construct", side_effect=construct), ExitStack() as stack:
            first = ConstructionManager(interval=0.02)
            second = ConstructionManager(interval=0.02)
            stack.callback(second.shutdown)
            stack.callback(first.shutdown)
            first.start()
            self.assertEqual(started.get(timeout=3), room.pk)
            # A second automatic or manual worker cannot enter construct while locked.
            with self.assertRaises(construction_workers.WorkerAlreadyRunning):
                construction_workers.run_worker(room.pk, True, io.StringIO(), io.StringIO())
            second.start()
            first.shutdown()
            self.assertEqual(started.get(timeout=3), room.pk)

    def test_background_worker_processes_posts_and_closes_its_client_on_shutdown(self):
        room = self.room("POST")
        loops, processed = [], Event()
        saved = set()

        async def initialize():
            loops.append(asyncio.get_running_loop())
            return SimpleNamespace(build_indices_and_constraints=AsyncMock())

        async def add(graph, family_id, text, name, at):
            saved.add(name)
            processed.set()

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
             patch.object(graphiti_client, "initialize_graphiti", new=AsyncMock(side_effect=initialize)), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()) as close, \
             patch.object(construction_workers, "sync_family"), \
             patch.object(construction_graphiti, "episode_names", new=AsyncMock(side_effect=lambda *args: set(saved))), \
             patch.object(construction_graphiti, "add_memory", new=AsyncMock(side_effect=add)) as store, \
             patch.object(construction_workers, "pause", side_effect=lambda stop: stop.wait(0.02)), ExitStack() as stack:
            manager = ConstructionManager(interval=60)
            stack.callback(manager.shutdown)
            manager.start()
            post = Post.objects.create(room=room, author=self.owner, caption="안부", description="저장할 소식")
            self.assertTrue(processed.wait(3))
        store.assert_awaited_once()
        self.assertEqual(store.await_args.args[1], room.pk)
        self.assertEqual(saved, {f"post_{post.pk}"})
        close.assert_awaited_once()
        self.assertTrue(loops[0].is_closed())


class ConstructionDisabledTests(SimpleTestCase):
    @override_settings(GRAPHITI_AUTO_CONSTRUCTION=False)
    def test_disabled_manager_never_starts_a_thread_or_queries_the_database(self):
        manager = ConstructionManager()
        manager.wake()
        manager.start()
        self.assertIsNone(manager._thread)
        manager.shutdown()
