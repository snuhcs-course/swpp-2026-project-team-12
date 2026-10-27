import assert from 'node:assert/strict';
import { test } from 'node:test';

globalThis.sessionStorage = { getItem: () => '', setItem() {}, removeItem() {} };
globalThis.window = new EventTarget();
const { api, hasToken, setToken } = await import('./assets/api.js');

test('proxy maintenance opens the notice while feature errors preserve the session and stay local', async () => {
  let notices = 0;
  window.addEventListener('server-maintenance', () => notices++);
  setToken('saved-login');
  for (const [result, expected] of [
    [null, 0],
    [{ error: '음성을 준비하지 못했어요.' }, 0],
    [{ code: 'maintenance', error: '서버를 점검 중이에요.' }, 1],
  ]) {
    globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => result });
    await assert.rejects(api('speech/', { method: 'POST', data: { text: '안녕' } }), error =>
      error.status === 503 && (result ? error.message === result.error : error.unavailable));
    assert.equal(notices, expected);
    assert.equal(hasToken(), true);
  }
});
