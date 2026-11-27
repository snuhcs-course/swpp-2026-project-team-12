"""Small, read-only dashboard. No additional server or storage dependency."""
from collections import Counter, defaultdict
from datetime import datetime, timezone as dt_timezone
import json
import math
import os
from pathlib import Path
import shutil
import threading
import time

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Count
from django.utils import timezone
from integrations.telemetry import FIELDS

MAX_RECORDS = 10000
_cpu_lock = threading.Lock()
_cpu_previous = None
_process_previous = {}
PUBLIC_FIELDS = FIELDS | {"timestamp", "event_id", "environment", "server_version", "schema_version",
                         "service", "pid", "thread", "level", "stack", "upstream_status", "upstream_ms", "connect_ms", "header_ms"}


def percentile(values, percentile):
    if not values:
        return None
    values = sorted(values)
    return round(values[max(0, math.ceil(len(values) * percentile) - 1)], 2)


def read_logs(directory, extra_paths=()):
    files = list(Path(directory).glob("*.jsonl*")) + [Path(p) for p in extra_paths]
    records, errors, truncated = [], 0, False
    files = sorted((p for p in files if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    truncated = len(files) > 32
    for path in files[:32]:
        try:
            with path.open('rb') as stream:
                size = path.stat().st_size
                offset = max(0, size - 1024 * 1024)
                stream.seek(offset)
                if offset:
                    stream.readline()  # Drop the partial leading line.
                    truncated = True
                for line in stream:
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict) or 'timestamp' not in row:
                            raise ValueError()
                        # nginx emits seconds; application logs already use milliseconds.
                        if row.get('component') == 'nginx':
                            for source, target in [('duration_seconds','duration_ms'), ('upstream_seconds','upstream_ms'), ('connect_seconds','connect_ms'), ('header_seconds','header_ms')]:
                                try:
                                    row[target] = float(row.get(source, '')) * 1000
                                except (ValueError, TypeError):
                                    row[target] = None
                        row['timestamp'] = datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')).astimezone(dt_timezone.utc).isoformat()
                        row = {k: v for k, v in row.items() if k in PUBLIC_FIELDS}
                        records.append(row)
                    except (ValueError, TypeError, UnicodeError):
                        errors += 1
        except OSError:
            errors += 1
    # Stable event IDs also deduplicate the brief overlap during log rotation.
    unique = {r.get('event_id') or (r.get('request_id'), r.get('component'), r['timestamp']): r for r in records}
    ordered = sorted(unique.values(), key=lambda r: r['timestamp'], reverse=True)
    return ordered[:MAX_RECORDS], errors, truncated or len(ordered) > MAX_RECORDS


def resources():
    global _cpu_previous
    result = {"cpu": None, "memory": None, "disk": None, "processes": []}
    try:
        values = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        total, idle = sum(values), values[3] + values[4]
        with _cpu_lock:
            if _cpu_previous and total > _cpu_previous[0]:
                result['cpu'] = round(100 * (1 - (idle - _cpu_previous[1]) / (total - _cpu_previous[0])), 1)
            _cpu_previous = total, idle
        mem = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
        result['memory'] = round(100 * (1 - mem['MemAvailable'] / mem['MemTotal']), 1)
    except (OSError, KeyError, ValueError):
        pass
    try:
        usage = shutil.disk_usage(settings.TELEMETRY_LOG_DIR)
        result['disk'] = round(100 * usage.used / usage.total, 1)
        result['disk_free_gb'] = round(usage.free / 1024**3, 1)
    except OSError:
        pass
    for path in Path(settings.TELEMETRY_STATE_DIR).glob('*.json'):
        try:
            row = json.loads(path.read_text())
            pid = int(row['pid'])
            os.kill(pid, 0)
            status = Path(f'/proc/{pid}/status').read_text()
            rss = next((int(line.split()[1]) / 1024 for line in status.splitlines() if line.startswith('VmRSS:')), 0)
            row['memory_mb'] = round(rss, 1)
            cpu_fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            cpu_seconds = (int(cpu_fields[11]) + int(cpu_fields[12])) / os.sysconf('SC_CLK_TCK')
            now = time.monotonic()
            previous = _process_previous.get(pid)
            row['cpu'] = round(100 * (cpu_seconds - previous[1]) / (now - previous[0]), 1) if previous and now > previous[0] else None
            _process_previous[pid] = now, cpu_seconds
            result['processes'].append(row)
        except (OSError, ValueError, KeyError):
            continue
    return result


def work_state():
    from .models import WorkItem
    from apps.notifications.models import PushNotification
    result = {"available": True, "jobs": [], "push": {}, "oldest_wait_ms": None}
    close_old_connections()
    try:
        result['jobs'] = list(WorkItem.objects.values('kind', 'status').annotate(count=Count('pk')))
        result['running'] = list(WorkItem.objects.filter(status='running').values('kind','started_at','attempts'))
        for job in result['running']:
            job['elapsed_ms'] = (timezone.now() - job.pop('started_at')).total_seconds() * 1000
        oldest = WorkItem.objects.exclude(status__in=['success', 'cancelled']).order_by('queued_at').first()
        if oldest:
            result['oldest_wait_ms'] = (timezone.now() - oldest.queued_at).total_seconds() * 1000
        result['push'] = dict(PushNotification.objects.values_list('status').annotate(count=Count('pk')))
    except Exception:
        # Show absence instead of replacing a DB failure with fabricated zeroes.
        result['available'] = False
    finally:
        close_old_connections()
    return result


def snapshot(params, extra_paths=()):
    rows, errors, truncated = read_logs(settings.TELEMETRY_LOG_DIR, extra_paths)
    minutes = min(1440, max(1, int(params.get('minutes', '60'))))
    since = time.time() - minutes * 60
    filtered = []
    facets = {key: sorted({str(r[key]) for r in rows if r.get(key)})
              for key in ('component', 'service', 'route', 'result')}
    for row in rows:
        try:
            if datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp() < since:
                continue
        except (ValueError, TypeError):
            errors += 1
            continue
        if any(params.get(k) and str(row.get(k, '')) != params[k] for k in facets):
            continue
        needle = params.get('id', '').strip().lower()
        if needle and not any(needle in str(row.get(k, '')).lower() for k in
                              ('operation_id', 'request_id', 'job_id', 'notification_id')):
            continue
        filtered.append(row)
    # A selected layer is required for request totals; workers are never counted as HTTP requests.
    layer = params.get('layer', 'django')
    http = [r for r in filtered if r.get('stage') == 'http_request' and r.get('component') == layer]
    durations = [float(r['duration_ms']) for r in http if isinstance(r.get('duration_ms'), (float, int))]
    failures = sum(int(r.get('http_status', 0)) >= 500 for r in http)
    apis, buckets = defaultdict(list), defaultdict(lambda: {'requests': 0, 'errors': 0})
    for row in http:
        apis[f"{row.get('method', '')} {row.get('route', 'unmatched')}"] .append(row)
        bucket = row['timestamp'][:16]
        buckets[bucket]['requests'] += 1
        buckets[bucket]['errors'] += int(int(row.get('http_status', 0)) >= 500)
    ranking = []
    for route, entries in apis.items():
        times = [r['duration_ms'] for r in entries if isinstance(r.get('duration_ms'), (float, int))]
        ranking.append({'route': route, 'count': len(entries), 'p50': percentile(times, .5), 'p95': percentile(times, .95)})
    limit = min(1000, max(100, int(params.get('limit', '100'))))
    return {'timestamp': datetime.now(dt_timezone.utc).isoformat(), 'hostname': os.uname().nodename,
            'environment': settings.TELEMETRY_ENVIRONMENT, 'layer': layer,
            'summary': {'requests': len(http), 'errors': failures, 'error_rate': round(failures / len(http) * 100, 2) if http else None,
                        'p50': percentile(durations, .5), 'p95': percentile(durations, .95)},
            'facets': facets, 'logs': filtered[:limit], 'matched': len(filtered), 'retained': len(rows),
            'parse_errors': errors, 'truncated': truncated, 'missing_logs': not rows,
            'series': [{'time': k, **v} for k, v in sorted(buckets.items())],
            'apis': sorted(ranking, key=lambda r: r['p95'] or 0, reverse=True),
            'resources': resources(), 'work': work_state()}
