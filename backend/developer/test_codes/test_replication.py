"""Real SQLite/filesystem round trips; no SSH credentials or external services required."""
import fcntl
import io
import json
import os
import sqlite3
import tarfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from integrations.replication import archive_snapshot, send_snapshot, snapshot, ssh_command
from integrations.replication_receiver import receive, safe_name


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    database = root / 'db.sqlite3'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE posts_post (id INTEGER PRIMARY KEY, images TEXT)')
        connection.execute('INSERT INTO posts_post VALUES (1, ?)', (json.dumps(['photos/photo.jpg']),))
    media = root / 'media'
    (media / 'photos').mkdir(parents=True)
    (media / 'photos/photo.jpg').write_bytes(b'photo fixture')
    (media / 'audio.wav').write_bytes(b'audio fixture')
    (media / '.graphiti-workers').mkdir()
    (media / '.graphiti-workers/worker.lock').write_text('runtime state')
    return root


@pytest.fixture
def standby(tmp_path):
    project = tmp_path / 'standby'
    (project / 'backend/media').mkdir(parents=True)
    (project / 'backend/manage.py').touch()
    (project / 'backend/db.sqlite3').write_bytes(b'existing standby database')
    (project / 'backend/media/existing.jpg').write_bytes(b'existing standby media')
    return project


def make_archive(source, directory):
    directory.mkdir()
    deadline = time.monotonic() + 30
    manifest = snapshot(source / 'db.sqlite3', source / 'media', directory / 'snapshot', deadline)
    archive = directory / 'snapshot.tar'
    archive_snapshot(directory / 'snapshot', manifest, archive, deadline)
    return manifest, archive


def deliver(archive, standby, keep=3):
    with archive.open('rb') as stream:
        return receive(stream, standby, keep)


def rewrite_archive(archive, transform):
    result = io.BytesIO()
    with tarfile.open(archive) as original, tarfile.open(fileobj=result, mode='w') as target:
        for member in original:
            content = original.extractfile(member).read()
            member, content = transform(member, content)
            if member is not None:
                member.size = len(content)
                target.addfile(member, io.BytesIO(content))
    result.seek(0)
    return result


def test_sqlite_media_round_trip_preserves_live_standby(source, standby, tmp_path):
    manifest, archive = make_archive(source, tmp_path / 'cycle')
    result = deliver(archive, standby)
    latest = standby / '.local/redundancy/latest'
    assert latest.is_symlink()
    assert result['snapshot_id'] == manifest['snapshot_id']
    assert result['files'] == 3
    assert result['bytes'] == sum(row['size'] for row in manifest['files'])
    assert (latest / 'media/photos/photo.jpg').read_bytes() == b'photo fixture'
    assert (latest / 'media/audio.wav').read_bytes() == b'audio fixture'
    assert not (latest / 'media/.graphiti-workers').exists()
    with sqlite3.connect(latest / 'db.sqlite3') as connection:
        assert connection.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        assert json.loads(connection.execute('SELECT images FROM posts_post').fetchone()[0]) == ['photos/photo.jpg']
    assert (standby / 'backend/db.sqlite3').read_bytes() == b'existing standby database'
    assert (standby / 'backend/media/existing.jpg').read_bytes() == b'existing standby media'
    assert not list((standby / '.local/redundancy').glob('.incoming-*'))
    assert (latest / 'db.sqlite3').stat().st_mode & 0o777 == 0o600


def test_sqlite_backup_includes_committed_wal_not_pending_transaction(source, tmp_path):
    with sqlite3.connect(source / 'db.sqlite3') as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('INSERT INTO posts_post VALUES (2, ?)', ('[]',))
        writer.commit()
        writer.execute('INSERT INTO posts_post VALUES (3, ?)', ('[]',))
        _, archive = make_archive(source, tmp_path / 'cycle')
        with tarfile.open(archive) as tar:
            data = tar.extractfile('db.sqlite3').read()
        copied = tmp_path / 'copied.sqlite3'
        copied.write_bytes(data)
        with sqlite3.connect(copied) as connection:
            assert connection.execute('SELECT id FROM posts_post ORDER BY id').fetchall() == [(1,), (2,)]
        writer.rollback()


@pytest.mark.parametrize('kind', ['missing', 'symlink'])
def test_missing_or_symlinked_required_media_rejects_snapshot(source, tmp_path, kind):
    photo = source / 'media/photos/photo.jpg'
    photo.unlink()
    if kind == 'symlink':
        secret = tmp_path / 'unrelated'
        secret.write_bytes(b'must not be copied')
        photo.symlink_to(secret)
    with pytest.raises(ValueError, match='Missing referenced media'):
        make_archive(source, tmp_path / 'cycle')


def test_unreferenced_symlinks_are_never_copied(source, tmp_path):
    (source / 'media/link').symlink_to('/etc')
    (source / 'media/file-link').symlink_to('/etc/passwd')
    manifest, _ = make_archive(source, tmp_path / 'cycle')
    assert {row['path'] for row in manifest['files']} == {'db.sqlite3', 'media/photos/photo.jpg', 'media/audio.wav'}


@pytest.mark.parametrize('failure', ['checksum', 'missing', 'truncated', 'symlink', 'traversal'])
def test_failed_transfer_keeps_previous_published_snapshot(source, standby, tmp_path, failure):
    _, original = make_archive(source, tmp_path / 'first')
    deliver(original, standby)
    latest = standby / '.local/redundancy/latest'
    before = latest.readlink()
    _, archive = make_archive(source, tmp_path / 'second')

    def tamper(member, content):
        if member.name == 'media/photos/photo.jpg':
            if failure == 'checksum':
                content = b'x' * len(content)
            elif failure == 'missing':
                return None, b''
            elif failure == 'symlink':
                member.type = tarfile.SYMTYPE
                member.linkname = '/etc/passwd'
                content = b''
            elif failure == 'traversal':
                member.name = '../../outside'
        return member, content

    stream = (io.BytesIO(archive.read_bytes()[:2000]) if failure == 'truncated'
              else rewrite_archive(archive, tamper))
    with pytest.raises((ValueError, tarfile.TarError, EOFError)):
        receive(stream, standby)
    assert latest.readlink() == before
    assert (latest / 'media/photos/photo.jpg').read_bytes() == b'photo fixture'
    assert not list((standby / '.local/redundancy').glob('.incoming-*'))


def test_receiver_checks_database_media_references(source, standby, tmp_path):
    manifest, archive = make_archive(source, tmp_path / 'cycle')

    def omit_photo(member, content):
        if member.name == 'manifest.json':
            manifest['files'] = [row for row in manifest['files'] if row['path'] != 'media/photos/photo.jpg']
            content = json.dumps(manifest).encode()
        if member.name == 'media/photos/photo.jpg':
            return None, b''
        return member, content

    with pytest.raises(ValueError, match='missing referenced media'):
        receive(rewrite_archive(archive, omit_photo), standby)
    assert not (standby / '.local/redundancy/latest').exists()


def test_retention_and_paused_destination(source, standby, tmp_path):
    identifiers = []
    for index in range(4):
        manifest, archive = make_archive(source, tmp_path / str(index))
        identifiers.append(manifest['snapshot_id'])
        deliver(archive, standby, keep=2)
    base = standby / '.local/redundancy'
    assert len(list((base / 'snapshots').iterdir())) == 2
    assert (base / 'latest').readlink().name == identifiers[-1]
    (base / 'PAUSED').touch()
    with pytest.raises(ValueError, match='paused'):
        deliver(archive, standby)
    assert (base / 'latest').readlink().name == identifiers[-1]


@pytest.mark.parametrize('name', ['../secret', 'media/../secret', '/media/a', 'media//a', 'media/./a', 'media/a\\b', 'media/', 'media', 'media/a\x00b'])
def test_reject_unsafe_archive_names(name):
    assert not safe_name(name)


def test_cycle_deadline_aborts_before_publication(source, tmp_path):
    with pytest.raises(TimeoutError):
        snapshot(source / 'db.sqlite3', source / 'media', tmp_path / 'snapshot', time.monotonic() - 1)


def test_ssh_setup_never_reads_private_key(tmp_path):
    config, key = tmp_path / 'config', tmp_path / 'key'
    config.write_text('Host swpp-b\n HostName 127.0.0.1\n IdentityFile ~/.ssh/example\n ProxyJump jump\n')
    key.touch()  # Dummy file; there are no real credentials in this test.
    original = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != key, 'Application code must never open the private key'
        return original(path, *args, **kwargs)

    with patch.object(Path, 'open', guarded_open):
        command = ssh_command(config, key, tmp_path / 'state', 'swpp-b', direct=True)
    assert 'ProxyJump=none' in command
    assert f'IdentityFile "{key}"' in (tmp_path / 'state/ssh_config').read_text()
    assert key.stat().st_mode & 0o777 == 0o600


def test_sender_rejects_wrong_acknowledgment(source, tmp_path):
    manifest, archive = make_archive(source, tmp_path / 'cycle')
    with patch('integrations.replication.subprocess.run') as run:
        run.return_value.returncode = 0
        run.return_value.stdout = b'{"schema_version":1,"snapshot_id":"wrong"}'
        with pytest.raises(ValueError, match='acknowledgment'):
            send_snapshot(['ssh', 'fake'], archive, manifest, '/tmp/project', 3, time.monotonic() + 10)


def test_command_duplicate_worker_and_read_only_status(tmp_path):
    state = tmp_path / 'state'
    state.mkdir()
    mask = os.umask(0o077)
    try:
        with (state / 'worker.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(CommandError, match='already running'):
                call_command('run_replication_worker', state_dir=str(state), once=True)
    finally:
        os.umask(mask)
    output = io.StringIO()
    call_command('run_replication_worker', state_dir=str(state), status=True, stdout=output)
    assert json.loads(output.getvalue())['state'] == 'never_started'


def test_command_local_transport_round_trip_and_failure_status(source, standby, tmp_path, settings):
    """Run the real receiver in a subprocess using SSH's remote-command argument contract."""
    state = tmp_path / 'worker'
    databases = {**settings.DATABASES, 'default': {**settings.DATABASES['default'], 'NAME': source / 'db.sqlite3'}}
    transport = ['sh', '-c', 'exec sh -c "$1"', 'test-ssh']
    command_module = 'apps.telemetry.management.commands.run_replication_worker'
    mask = os.umask(0o077)
    try:
        with override_settings(DATABASES=databases, MEDIA_ROOT=source / 'media'):
            with patch(command_module + '.ssh_command', return_value=transport):
                call_command('run_replication_worker', state_dir=str(state), remote_project=str(standby),
                             once=True, stdout=io.StringIO())
            status = json.loads((state / 'status.json').read_text())
            assert status['last_error'] is None
            assert status['files'] == 3
            assert status['snapshot_id'] == (standby / '.local/redundancy/latest').readlink().name
            with patch(command_module + '.ssh_command', return_value=['false']):
                with pytest.raises(CommandError, match='SSH/receiver failed'):
                    call_command('run_replication_worker', state_dir=str(state), remote_project=str(standby),
                                 once=True, stderr=io.StringIO())
            failed = json.loads((state / 'status.json').read_text())
            assert failed['last_success'] == status['last_success']
            assert failed['last_failure']
            assert 'SSH/receiver failed' in failed['last_error']
            assert not list(state.glob('cycle-*'))
    finally:
        os.umask(mask)
