from contextlib import contextmanager
import fcntl
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from apps.telemetry.dashboard import read_logs, replication_state, snapshot
from apps.telemetry.management.commands.run_telemetry_dashboard import handler


class DashboardTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = override_settings(TELEMETRY_LOG_DIR=Path(self.directory.name),
                                                  TELEMETRY_STATE_DIR=self.directory.name,
                                                  BASE_DIR=Path(self.directory.name) / 'backend')
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.rows = [dict(event_id=str(i), timestamp=datetime.now(timezone.utc).isoformat(),
                         component='django', stage='http_request', http_status=500 if i==2 else 200,
                         duration_ms=duration, route='api/posts/', operation_id='operation-one',
                         body='PRIVATE', token='PRIVATE') for i, duration in enumerate([10, 20, 90])]
        self.rows.append(dict(self.rows[0], event_id='nginx', component='nginx', duration_ms=100))
        Path(self.directory.name, 'sample.jsonl').write_text('\n'.join(map(json.dumps,self.rows))+'\ninvalid\n')
        self.replication_dir = Path(self.directory.name) / '.local/redundancy/worker'
        self.replication_dir.mkdir(parents=True)

    def write_replication(self, **overrides):
        status = {'pid': os.getpid(), 'host': 'swpp-b', 'state': 'running', 'interval': 60,
                  'last_success': '2026-11-26T18:00:00+00:00', 'files': 237,
                  'bytes': 58641240, 'duration_ms': 1850, 'last_error': None,
                  'ignored_private_field': 'PRIVATE'}
        status.update(overrides)
        (self.replication_dir / 'status.json').write_text(json.dumps(status))

    @contextmanager
    def running_replication(self):
        with (self.replication_dir / 'worker.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def test_replication_acknowledged_success_and_filter_independence(self):
        self.write_replication()
        now = datetime.fromisoformat('2026-11-26T18:00:30+00:00').timestamp()
        with self.running_replication(), patch('apps.telemetry.dashboard.time.time', return_value=now), \
                patch('apps.telemetry.dashboard.work_state', return_value={'available': True}):
            result = snapshot({'id': 'no-matching-id', 'service': 'api'})['replication']
        self.assertEqual(result['state'], 'healthy')
        self.assertTrue(result['running'])
        self.assertEqual(result['last_success'], '2026-11-26T18:00:00+00:00')
        self.assertEqual(result['age_seconds'], 30)
        self.assertEqual(result['files'], 237)
        self.assertEqual(result['bytes'], 58641240)
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_replication_recent_failure_preserves_previous_success(self):
        self.write_replication(last_error='SSH/receiver failed: connection refused')
        with self.running_replication():
            result = replication_state()
        self.assertEqual(result['state'], 'error')
        self.assertEqual(result['last_success'], '2026-11-26T18:00:00+00:00')
        self.assertIn('connection refused', result['last_error'])

    def test_replication_stale_uses_configured_interval(self):
        self.write_replication(interval=30)
        success = datetime.fromisoformat('2026-11-26T18:00:00+00:00').timestamp()
        with self.running_replication(), patch('apps.telemetry.dashboard.time.time', return_value=success + 61):
            result = replication_state()
        self.assertEqual(result['state'], 'stale')
        self.assertEqual(result['stale_after_seconds'], 60)

    def test_replication_stopped_even_if_saved_pid_is_alive(self):
        self.write_replication()
        self.assertEqual(replication_state()['state'], 'stopped')
        with self.running_replication():
            self.assertTrue(replication_state()['running'])
        self.assertFalse(replication_state()['running'])

    def test_replication_not_started_and_first_cycle(self):
        self.assertEqual(replication_state()['state'], 'not_started')
        with self.running_replication():
            result = replication_state()
        self.assertEqual(result['state'], 'starting')
        self.assertIsNone(result['last_success'])

    def test_invalid_replication_status_does_not_break_dashboard(self):
        for content in ('{partial', '[]', '{"interval": "NaN"}', '{"interval": 1e308}',
                        '{"last_success": "yesterday"}', '{"last_success": "2026-11-26T18:00:00"}'):
            with self.subTest(content=content):
                (self.replication_dir / 'status.json').write_text(content)
                with patch('apps.telemetry.dashboard.work_state', return_value={'available': True}):
                    result = snapshot({})
                self.assertEqual(result['replication']['state'], 'unavailable')
                json.dumps(result, allow_nan=False)

    def test_real_log_filter_percentiles_and_layer_isolation(self):
        with patch('apps.telemetry.dashboard.work_state', return_value={'available':True}):
            data = snapshot({'minutes':'15'})
            self.assertEqual(data['summary']['requests'], 3)
            self.assertEqual(data['summary']['p50'], 20)
            self.assertEqual(data['summary']['p95'], 90)
            self.assertEqual(data['summary']['error_rate'], 33.33)
            self.assertEqual(data['parse_errors'], 1)
            self.assertNotIn('PRIVATE', json.dumps(data))
            filtered = snapshot({'id':'does-not-exist'})
            self.assertIsNone(filtered['summary']['p95'])
            self.assertEqual(filtered['matched'], 0)
            self.assertEqual(snapshot({'layer':'nginx'})['summary']['requests'],1)

    def test_rotation_overlap_is_deduplicated(self):
        Path(self.directory.name, 'sample.jsonl.1').write_text(json.dumps(self.rows[0])+'\n')
        self.assertEqual(len(read_logs(self.directory.name)[0]),4)

    def test_real_http_read_only_and_host_check(self):
        server = ThreadingHTTPServer(('127.0.0.1',0),handler())
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        with urlopen(base) as response:
            self.assertIn(b'Event explorer',response.read())
            self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(base,headers={'Host':'attacker.example'}))
        self.assertEqual(error.exception.code,403)
        with patch('apps.telemetry.dashboard.work_state',return_value={'available':True}):
            with urlopen(base+'/api/snapshot?minutes=15') as response:
                data = json.load(response)
                self.assertEqual(data['summary']['requests'],3)
                self.assertEqual(data['replication']['state'], 'not_started')
        with self.assertRaises(HTTPError) as error:
            urlopen(base+'/api/snapshot?minutes=invalid')
        self.assertEqual(error.exception.code,400)
