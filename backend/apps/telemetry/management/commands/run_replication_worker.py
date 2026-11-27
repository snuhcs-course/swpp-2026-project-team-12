from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import tempfile
from threading import Event
import time
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from integrations.replication import snapshot, archive_snapshot, ssh_command, send_snapshot
from integrations.telemetry import emit, runtime


class Command(BaseCommand):
    help = 'Replicate consistent SQLite + media snapshots over SSH every 60 seconds. Never starts the standby app.'

    def add_arguments(self, parser):
        root = settings.BASE_DIR.parent
        parser.add_argument('--host', default='swpp-b')
        parser.add_argument('--ssh-config', default=str(root.parent / 'redundancy/ssh_config'))
        parser.add_argument('--ssh-key', default=str(root.parent / 'redundancy/swpp26-13'))
        parser.add_argument('--remote-project', default=str(root))
        parser.add_argument('--state-dir', default=str(root / '.local/redundancy/worker'))
        parser.add_argument('--direct', action='store_true', help='Connect directly on the internal network, bypassing ProxyJump.')
        parser.add_argument('--interval', type=float, default=60)
        parser.add_argument('--timeout', type=float, default=55)
        parser.add_argument('--keep', type=int, default=3)
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--once', action='store_true')
        group.add_argument('--status', action='store_true')

    def handle(self, *args, **options):
        state = Path(options['state_dir']).resolve()
        status_file = state / 'status.json'
        if options['status']:
            self.stdout.write(status_file.read_text() if status_file.exists() else '{"state":"never_started"}')
            return
        if options['interval'] <= 0 or options['timeout'] <= 0 or options['keep'] < 1:
            raise CommandError('interval, timeout and keep must be positive')
        if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
            raise CommandError('Replication currently supports SQLite only')
        os.umask(0o077)
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (state / 'worker.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CommandError('A replication cycle or worker is already running in this state directory') from error
            command = ssh_command(options['ssh_config'], options['ssh_key'], state, options['host'], options['direct'])
            stopped = Event()
            previous = {sig: signal.signal(sig, lambda *_: stopped.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
            status = json.loads(status_file.read_text()) if status_file.exists() else {}
            status.update(pid=os.getpid(), state='running', host=options['host'], interval=options['interval'])
            try:
                next_run = time.monotonic()
                while not stopped.is_set():
                    started = time.monotonic()
                    runtime('replication', last_poll=time.time())
                    try:
                        with tempfile.TemporaryDirectory(prefix='cycle-', dir=state) as directory:
                            deadline = started + options['timeout']
                            manifest = snapshot(settings.DATABASES['default']['NAME'], settings.MEDIA_ROOT,
                                                Path(directory) / 'snapshot', deadline)
                            archive = Path(directory) / 'snapshot.tar'
                            archive_snapshot(Path(directory) / 'snapshot', manifest, archive, deadline)
                            result = send_snapshot(command, archive, manifest, options['remote_project'], options['keep'], deadline)
                        status.update(state='running', last_success=datetime.now(timezone.utc).isoformat(),
                                      snapshot_id=result['snapshot_id'], remote_path=result['path'],
                                      files=result['files'], bytes=result['bytes'], last_error=None)
                        runtime('replication', last_success=time.time(), bytes=result['bytes'])
                        emit('replication_complete', component='replication', result='success',
                             count=result['files'], bytes=result['bytes'], duration_ms=(time.monotonic()-started)*1000)
                        self.stdout.write(f"{status['last_success']} replicated {result['snapshot_id']}: {result['files']} files, {result['bytes']} bytes", ending='\n')
                    except Exception as error:
                        status.update(state='error', last_error=type(error).__name__ + ': ' + str(error),
                                      last_failure=datetime.now(timezone.utc).isoformat())
                        emit('replication_complete', component='replication', result='error', error_type=type(error).__name__)
                        self.stderr.write(status['last_error'])
                        if options['once']:
                            raise CommandError(status['last_error']) from error
                    finally:
                        status['duration_ms'] = round((time.monotonic()-started)*1000, 2)
                        temporary = state / 'status.tmp'
                        temporary.write_text(json.dumps(status, indent=2)+'\n')
                        temporary.replace(status_file)
                    if options['once']:
                        break
                    next_run += options['interval']
                    if next_run < time.monotonic():
                        next_run += (int((time.monotonic()-next_run)/options['interval'])+1)*options['interval']
                    stopped.wait(max(0, next_run-time.monotonic()))
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
                status['state'] = 'stopped'
                status_file.write_text(json.dumps(status, indent=2)+'\n')
