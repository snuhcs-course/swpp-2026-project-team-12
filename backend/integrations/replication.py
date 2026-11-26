"""Consistent SQLite backup + bounded local media snapshot + verified SSH publication."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import tarfile
import time
import uuid

from .replication_receiver import media_references


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError('Replication cycle deadline exceeded')


def snapshot(database, media, directory, deadline):
    database, media, directory = Path(database).resolve(), Path(media).resolve(), Path(directory)
    if not database.is_file() or not media.is_dir():
        raise ValueError('Source SQLite file and media directory must exist')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / 'db.sqlite3'
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5) as source:
        with sqlite3.connect(destination) as target:
            source.backup(target, pages=256, progress=lambda *_: check_deadline(deadline), sleep=.01)
            if target.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('Source snapshot integrity check failed')
    required = media_references(destination)
    files = []
    for folder, subdirs, names in os.walk(media, followlinks=False):
        subdirs[:] = sorted(name for name in subdirs if name != '.graphiti-workers'
                           and not (Path(folder) / name).is_symlink())
        for name in sorted(names):
            check_deadline(deadline)
            source = Path(folder) / name
            relative = Path('media') / source.relative_to(media)
            if source.is_symlink() or not source.is_file():
                continue
            output = directory / relative
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                before = source.stat()
                with source.open('rb') as input_file, output.open('xb') as output_file:
                    digest = hashlib.sha256()
                    while chunk := input_file.read(1024**2):
                        check_deadline(deadline)
                        digest.update(chunk)
                        output_file.write(chunk)
                after = source.stat()
                if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                    raise ValueError('Media changed while being snapshotted')
                files.append({'path': relative.as_posix(), 'size': before.st_size, 'sha256': digest.hexdigest()})
            except FileNotFoundError:
                output.unlink(missing_ok=True)
                if relative.as_posix() in required:
                    raise
                # An unreferenced upload/cache can disappear before the DB uses it.
    if not required <= {row['path'] for row in files}:
        raise ValueError('Missing referenced media; retaining previous remote snapshot')
    digest = hashlib.sha256()
    with destination.open('rb') as source:
        while chunk := source.read(1024**2):
            check_deadline(deadline)
            digest.update(chunk)
    files.insert(0, {'path': 'db.sqlite3', 'size': destination.stat().st_size, 'sha256': digest.hexdigest()})
    snapshot_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
    return {'schema_version': 1, 'snapshot_id': snapshot_id,
            'created_at': datetime.now(timezone.utc).isoformat(), 'files': files}


def archive_snapshot(directory, manifest, destination, deadline):
    with tarfile.open(destination, 'w') as archive:
        content = json.dumps(manifest, ensure_ascii=False).encode()
        entry = tarfile.TarInfo('manifest.json')
        entry.size = len(content)
        entry.mode = 0o600
        archive.addfile(entry, io.BytesIO(content))
        for row in manifest['files']:
            check_deadline(deadline)
            archive.add(Path(directory) / row['path'], arcname=row['path'], recursive=False)


def ssh_command(config, key, state, host, direct=False):
    """Read config only. The private key is inspected by stat/chmod and used by ssh itself."""
    config, key, state = Path(config).resolve(), Path(key).resolve(), Path(state)
    if not config.is_file() or not key.is_file() or host.startswith('-') or not re.fullmatch(r'[\w@.:-]+', host):
        raise ValueError('Invalid SSH configuration, identity path or destination')
    key.chmod(0o600)
    text = config.read_text()
    # ProxyJump launches another ssh process, so -i on the final hop alone is insufficient.
    text = '\n'.join('  IdentityFile "' + str(key).replace('\\', '\\\\').replace('"', '\\"') + '"'
                     if line.strip().lower().startswith('identityfile ') else line
                     for line in text.splitlines()) + '\n'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    effective = state / 'ssh_config'
    effective.write_text(text)
    effective.chmod(0o600)
    command = ['ssh', '-F', str(effective), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new',
               '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
               '-i', str(key)]
    if direct:
        command += ['-o', 'ProxyJump=none']
    return command + [host]


def send_snapshot(command, archive, manifest, remote_project, keep, deadline):
    if not Path(remote_project).is_absolute() or remote_project == '/' or keep < 1:
        raise ValueError('Expected an absolute remote project path and positive retention')
    receiver = Path(__file__).with_name('replication_receiver.py').read_text()
    remote = 'python3 -c ' + shlex.quote(receiver) + ' ' + shlex.quote(remote_project) + ' ' + str(keep)
    check_deadline(deadline)
    with Path(archive).open('rb') as stream:
        result = subprocess.run(command + [remote], stdin=stream, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=max(.1, deadline - time.monotonic()))
    if result.returncode:
        # SSH diagnostics contain no input DB or media contents; cap output for operators.
        raise RuntimeError('SSH/receiver failed: ' + result.stderr.decode(errors='replace')[-1500:].strip())
    lines = result.stdout.decode().strip().splitlines()
    acknowledgment = json.loads(lines[-1] if lines else '{}')
    if (acknowledgment.get('snapshot_id') != manifest['snapshot_id'] or acknowledgment.get('schema_version') != 1
            or acknowledgment.get('files') != len(manifest['files'])
            or acknowledgment.get('bytes') != sum(row['size'] for row in manifest['files'])):
        raise ValueError('Invalid remote snapshot acknowledgment')
    return acknowledgment
