"""Optional real-browser integration check: python backend/developer/check_telemetry_browser.py."""
from datetime import datetime, timedelta, timezone
import fcntl
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
        state = Path(directory) / '.local/redundancy/worker'
        state.mkdir(parents=True)

        def replication_status(age=30, error=None):
            status = {'host': 'swpp-b', 'interval': 60,
                      'last_success': (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
                      'files': 237, 'bytes': 58641240, 'duration_ms': 1850, 'last_error': error}
            (state / 'status.json').write_text(json.dumps(status))
            return status

        replication_status()
        with (state / 'worker.lock').open('a') as replication_lock, \
             override_settings(TELEMETRY_LOG_DIR=Path(directory), TELEMETRY_STATE_DIR=directory,
                               BASE_DIR=Path(directory) / 'backend'), \
             patch('apps.telemetry.dashboard.work_state', return_value={'available':True,'jobs':[],'push':{}}):
            fcntl.flock(replication_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
                    expect(page.locator('#replicationBadge')).to_have_text('정상')
                    expect(page.locator('#replicationTarget')).to_contain_text('swpp-b')
                    expect(page.locator('#replicationFiles')).to_have_text('237개 파일')
                    expect(page.locator('#replicationAge')).to_contain_text('초 전')
                    expect(page.locator('#replicationLastSuccess')).not_to_have_text('—')
                    page.locator('#pause').click()
                    page.locator('#more').click()
                    expect(page.locator('#events tr.log')).to_have_count(115)
                    page.locator('tr.log').first.click()
                    expect(page.locator('pre')).to_have_count(1)
                    page.locator('#id').fill('no-matching-id')
                    page.locator('#id').dispatch_event('change')
                    expect(page.locator('#logCount')).to_have_text('0 / 0 events')
                    # Backup state remains visible even when event filters match nothing.
                    expect(page.locator('#replicationBadge')).to_have_text('정상')
                    page.locator('#reset').click()
                    expect(page.locator('#events tr.log')).to_have_count(100)
                    replication_status(age=180)
                    page.locator('#refresh').click()
                    expect(page.locator('#replicationBadge')).to_have_text('복제 지연')
                    replication_status(error='SSH failed <img src=x onerror=alert(1)>')
                    page.locator('#refresh').click()
                    expect(page.locator('#replicationBadge')).to_have_text('최근 복제 실패')
                    expect(page.locator('#replicationDetail')).to_contain_text('SSH failed <img')
                    expect(page.locator('#replicationDetail img')).to_have_count(0)
                    fcntl.flock(replication_lock, fcntl.LOCK_UN)
                    page.locator('#refresh').click()
                    expect(page.locator('#replicationBadge')).to_have_text('워커 중지')
                    fcntl.flock(replication_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    status = replication_status()
                    page.locator('#refresh').click()
                    expect(page.locator('#replicationBadge')).to_have_text('정상')
                    expected_time = page.evaluate('value => new Date(value).toLocaleString("ko-KR", {timeZone:"Asia/Seoul", hour12:false})', status['last_success'])
                    expect(page.locator('#replicationLastSuccess')).to_have_text(expected_time)
                    page.locator('#theme').click()
                    expect(page.locator('html')).to_have_attribute('data-theme','light')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('() => document.body.scrollWidth <= innerWidth')
                    assert not errors, errors
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
    print('Telemetry browser integration passed: filters, pagination, details, replication states/KST, themes, mobile, no JS errors.')


if __name__ == '__main__':
    main()
