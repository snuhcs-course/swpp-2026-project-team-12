"""Standalone stdlib receiver, sent over SSH. Never imports or starts the remote app."""
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import uuid

SNAPSHOT_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{12}\Z")


def media_references(database):
    """Read only paths, never content, from the *snapshotted* app DB."""
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(posts_post)')}
        if 'images' not in columns:
            raise ValueError('Expected current posts_post.images schema; migrate the source first')
        result = set()
        for (images,) in connection.execute('SELECT images FROM posts_post'):
            images = json.loads(images)
            if not isinstance(images, list):
                raise ValueError('Invalid images field')
            for name in images:
                if not isinstance(name, str) or not name or not safe_name('media/' + name):
                    raise ValueError('Unsafe media reference in snapshot')
                result.add('media/' + name)
        return result


def safe_name(name):
    if not isinstance(name, str) or '\\' in name or '\x00' in name:
        return False
    path = PurePosixPath(name)
    return (name == 'db.sqlite3' or
            (name.startswith('media/') and len(path.parts) > 1)) and not (
                path.is_absolute() or '..' in path.parts or str(path) != name)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def receive(stream, project, keep=3):
    project = Path(project).resolve()
    if not (project / 'backend/manage.py').is_file() or keep < 1:
        raise ValueError('Expected a TalkDock project and positive retention')
    base = project / '.local/redundancy'
    if not base.resolve().is_relative_to(project):
        raise ValueError('Backup directory must stay inside the project')
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshots = base / 'snapshots'
    snapshots.mkdir(exist_ok=True, mode=0o700)
    if snapshots.is_symlink():
        raise ValueError('Snapshots directory cannot be a symlink')
    # An operator can put this marker here before promoting B to reject further replication.
    if (base / 'PAUSED').exists():
        raise ValueError('Replication is paused on the destination')
    with (base / '.receive.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix='.incoming-', dir=base) as incoming:
            incoming = Path(incoming)
            with tarfile.open(fileobj=stream, mode='r|') as archive:
                first = archive.next()
                if first is None or first.name != 'manifest.json' or not first.isfile() or first.size > 8 * 1024**2:
                    raise ValueError('A bounded manifest must be the first regular file')
                manifest = json.load(archive.extractfile(first))
                snapshot_id = manifest.get('snapshot_id', '')
                if manifest.get('schema_version') != 1 or not SNAPSHOT_ID.fullmatch(snapshot_id):
                    raise ValueError('Invalid snapshot manifest')
                expected = {}
                for row in manifest['files']:
                    name, size, digest = row['path'], row['size'], row['sha256']
                    if (not safe_name(name) or name in expected or type(size) is not int or size < 0
                            or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
                        raise ValueError('Invalid file manifest')
                    expected[name] = row
                if 'db.sqlite3' not in expected:
                    raise ValueError('Missing SQLite snapshot')
                total = sum(row['size'] for row in expected.values())
                if total + 64 * 1024**2 > shutil.disk_usage(base).free:
                    raise ValueError('Insufficient destination disk space')
                seen = set()
                while True:
                    member = archive.next()
                    if member is None:
                        break
                    if (not member.isfile() or member.name not in expected or member.name in seen
                            or member.size != expected[member.name]['size']):
                        raise ValueError('Unexpected archive member')
                    destination = incoming / member.name
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    digest = hashlib.sha256()
                    with archive.extractfile(member) as source, destination.open('xb') as output:
                        while chunk := source.read(1024**2):
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if digest.hexdigest() != expected[member.name]['sha256']:
                        raise ValueError('File checksum mismatch')
                    destination.chmod(0o600)
                    seen.add(member.name)
            if seen != set(expected):
                raise ValueError('Incomplete snapshot')
            database = incoming / 'db.sqlite3'
            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
                if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise ValueError('SQLite integrity check failed')
            if not media_references(database) <= seen:
                raise ValueError('Snapshot is missing referenced media')
            (incoming / 'media').mkdir(exist_ok=True, mode=0o700)
            with (incoming / 'manifest.json').open('x') as output:
                json.dump(manifest, output)
                output.flush()
                os.fsync(output.fileno())
            if (base / 'PAUSED').exists():
                raise ValueError('Destination paused before publication')
            for folder, _, _ in os.walk(incoming, topdown=False):
                sync_directory(folder)
            final = snapshots / snapshot_id
            if final.exists():
                raise ValueError('Snapshot ID already exists')
            incoming.rename(final)
            sync_directory(snapshots)
            link = base / ('.latest-' + uuid.uuid4().hex)
            try:
                link.symlink_to(Path('snapshots') / snapshot_id)
                os.replace(link, base / 'latest')
                sync_directory(base)
            finally:
                link.unlink(missing_ok=True)
        # Only delete our validated snapshot generations; never the project's app DB/media.
        old = sorted((p for p in snapshots.iterdir() if SNAPSHOT_ID.fullmatch(p.name)
                      and p.is_dir() and not p.is_symlink() and (p / 'manifest.json').is_file()),
                     key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
        for path in [p for p in old if p != final][keep - 1:]:
            try:
                shutil.rmtree(path)
            except OSError:
                # The new verified backup is already published; cleanup can retry next cycle.
                print('Warning: could not remove an old snapshot', file=sys.stderr)
        return {'snapshot_id': snapshot_id, 'files': len(seen), 'bytes': total,
                'path': str(base / 'latest'), 'schema_version': 1}


if __name__ == '__main__':
    os.umask(0o077)
    try:
        result = receive(sys.stdin.buffer, sys.argv[1], int(sys.argv[2]))
        print(json.dumps(result), flush=True)
    except Exception as error:
        # Keep errors useful without printing SQL rows, filenames or archive contents.
        print('Replica receive failed: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr)
        sys.exit(1)
