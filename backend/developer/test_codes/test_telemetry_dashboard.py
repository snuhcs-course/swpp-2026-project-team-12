import json
import tempfile
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from apps.telemetry.dashboard import read_logs, snapshot
from apps.telemetry.management.commands.run_telemetry_dashboard import handler


class DashboardTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = override_settings(TELEMETRY_LOG_DIR=Path(self.directory.name),
                                                  TELEMETRY_STATE_DIR=self.directory.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.rows = [dict(event_id=str(i), timestamp=datetime.now(timezone.utc).isoformat(),
                         component='django', stage='http_request', http_status=500 if i==2 else 200,
                         duration_ms=duration, route='api/posts/', operation_id='operation-one',
                         body='PRIVATE', token='PRIVATE') for i, duration in enumerate([10, 20, 90])]
        self.rows.append(dict(self.rows[0], event_id='nginx', component='nginx', duration_ms=100))
        Path(self.directory.name, 'sample.jsonl').write_text('\n'.join(map(json.dumps,self.rows))+'\ninvalid\n')

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
                self.assertEqual(json.load(response)['summary']['requests'],3)
        with self.assertRaises(HTTPError) as error:
            urlopen(base+'/api/snapshot?minutes=invalid')
        self.assertEqual(error.exception.code,400)
