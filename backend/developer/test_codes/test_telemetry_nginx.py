"""Actual nginx proxy/maintenance integration, without touching the running server."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from threading import Thread
import time
from unittest import skipUnless
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from django.test import SimpleTestCase


@skipUnless(shutil.which('nginx'), 'nginx is required for this integration check')
class NginxTelemetryTests(SimpleTestCase):
    def test_proxy_maintenance_failure_ids_and_private_query(self):
        received=[]
        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(dict(self.headers))
                self.send_response(503 if self.path.startswith('/api/speech/') else 200)
                self.send_header('X-Request-ID','forged-upstream')
                self.end_headers()
                self.wfile.write(b'{}')
            def log_message(self,*args):
                pass
        upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        Thread(target=upstream.serve_forever,daemon=True).start()
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0)); port=reservation.getsockname()[1]
        template=Path(__file__).resolve().parents[3]/'deploy'/'nginx'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'run').mkdir()
            for name in ['maintenance.json','maintenance.html']:
                shutil.copyfile(template/name,root/name)
            config=(template/'nginx.conf').read_text().replace('127.0.0.1:8080',f'127.0.0.1:{port}').replace('127.0.0.1:8002',f'127.0.0.1:{upstream.server_port}')
            (root/'nginx.conf').write_text(config)
            process=subprocess.Popen(['nginx','-p',str(root)+'/', '-c','nginx.conf','-g','daemon off;'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                for _ in range(50):
                    try:
                        with socket.create_connection(('127.0.0.1',port),.1):
                            break
                    except OSError:
                        time.sleep(.05)
                base=f'http://127.0.0.1:{port}'
                op='12345678-1234-1234-1234-123456789abc'
                with urlopen(Request(base+'/api/test_reply/?query=PRIVATE',headers={'X-Operation-ID':op,'X-Request-ID':'forged-client'})) as response:
                    request_id=response.headers['X-Request-ID']
                    self.assertNotEqual(request_id,'forged-client')
                    self.assertNotEqual(request_id,'forged-upstream')
                    self.assertEqual(received[-1]['X-Request-ID'],request_id)
                with self.assertRaises(HTTPError) as feature:
                    urlopen(base+'/api/speech/')
                self.assertEqual(feature.exception.code,503)
                (root/'maintenance.flag').touch()
                with self.assertRaises(HTTPError) as maintenance:
                    urlopen(base+'/api/test_reply/')
                self.assertEqual(maintenance.exception.code,503)
                self.assertTrue(maintenance.exception.headers.get('X-Request-ID'))
                (root/'maintenance.flag').unlink()
                upstream.shutdown(); upstream.server_close()
                with self.assertRaises(HTTPError) as unavailable:
                    urlopen(base+'/api/test_reply/')
                self.assertEqual(unavailable.exception.code,503)
            finally:
                process.terminate()
                process.communicate(timeout=10)
            raw=(root/'run'/'access.log').read_text()
            self.assertNotIn('PRIVATE',raw)
            rows=[json.loads(line) for line in raw.splitlines()]
            self.assertEqual(rows[0]['request_id'],request_id)
            self.assertEqual(rows[0]['operation_id'],op)
            self.assertEqual([row['reason'] for row in rows],['','django_feature_error','maintenance','upstream_error'])
