import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from django.core.management.base import BaseCommand
from apps.telemetry.dashboard import snapshot


def handler(extra_paths=()):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Loopback binding plus Host validation prevents browser DNS rebinding.
            if self.headers.get('Host', '').split(':')[0] not in {'localhost', '127.0.0.1'}:
                self.send_error(403)
                return
            url = urlsplit(self.path)
            if url.path == '/':
                data = (Path(__file__).resolve().parents[2] / 'dashboard.html').read_bytes()
                content_type, status = 'text/html; charset=utf-8', 200
            elif url.path == '/api/snapshot':
                try:
                    params = {k: v[0] for k, v in parse_qs(url.query).items()}
                    data = json.dumps(snapshot(params, extra_paths), allow_nan=False).encode()
                    content_type, status = 'application/json', 200
                except (ValueError, TypeError):
                    data, content_type, status = b'{"error":"Invalid filter"}', 'application/json', 400
            else:
                self.send_error(404)
                return
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass  # IDs and filters are not access-log payloads.
    return Handler


class Command(BaseCommand):
    help = 'Read local telemetry in a browser over an SSH tunnel. Ctrl+C stops it.'

    def add_arguments(self, parser):
        parser.add_argument('--port', type=int, default=8765)
        parser.add_argument('--nginx-log', action='append', default=[])

    def handle(self, *args, **options):
        server = ThreadingHTTPServer(('127.0.0.1', options['port']), handler(options['nginx_log']))
        self.stdout.write(f"Telemetry dashboard: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
