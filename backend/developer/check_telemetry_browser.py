"""Optional real-browser integration check: python backend/developer/check_telemetry_browser.py."""
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'configs.settings')
import django
django.setup()
from django.test import override_settings
from apps.telemetry.management.commands.run_telemetry_dashboard import handler
from playwright.sync_api import sync_playwright, expect


def main():
    with tempfile.TemporaryDirectory() as directory:
        records = [dict(timestamp=datetime.now(timezone.utc).isoformat(), event_id=str(i),
                        component='django', service='api', stage='http_request', result='success',
                        method='GET', route='api/test_reply/', http_status=200, duration_ms=i+1,
                        operation_id=f'operation-{i}') for i in range(115)]
        Path(directory, 'test.jsonl').write_text('\n'.join(map(json.dumps, records))+'\n')
        with override_settings(TELEMETRY_LOG_DIR=Path(directory), TELEMETRY_STATE_DIR=directory), \
             patch('apps.telemetry.dashboard.work_state', return_value={'available':True,'jobs':[],'push':{}}):
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler())
            Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width':1440,'height':1000})
                    errors=[]
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}')
                    expect(page.locator('#events tr.log')).to_have_count(100)
                    page.locator('#pause').click()
                    page.locator('#more').click()
                    expect(page.locator('#events tr.log')).to_have_count(115)
                    page.locator('tr.log').first.click()
                    expect(page.locator('pre')).to_have_count(1)
                    page.locator('#id').fill('no-matching-id')
                    page.locator('#id').dispatch_event('change')
                    expect(page.locator('#logCount')).to_have_text('0 / 0 events')
                    page.locator('#reset').click()
                    expect(page.locator('#events tr.log')).to_have_count(100)
                    page.locator('#theme').click()
                    expect(page.locator('html')).to_have_attribute('data-theme','light')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('() => document.body.scrollWidth <= innerWidth')
                    assert not errors, errors
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
    print('Telemetry browser integration passed: filters, reset race, pagination, details, themes, mobile, no JS errors.')


if __name__ == '__main__':
    main()
