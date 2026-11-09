// Run: node --test web/test_usability.mjs (offline; no accounts or API keys required).
import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

const storage = new Map();
globalThis.sessionStorage = { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
let events;
globalThis.window = { location: { origin: 'https://web.example' }, dispatchEvent: event => events.push(event.type) };
const { api, ApiError, registrationPayload, availabilityMessages, setToken, hasToken } = await import('./assets/api.js');
const signup = () => ({ username: 'offline-person', name: '가족', gender: 'female', password: 'Family-Test-123!', confirm_password: 'Family-Test-123!' });
let requests;
const response = (status, result, { html = false } = {}) => ({
  ok: status >= 200 && status < 300, status,
  json: async () => { if (html) throw new SyntaxError('HTML response'); return result; },
  blob: async () => new Blob(['audio'], { type: 'audio/mpeg' }),
});
beforeEach(() => {
  events = []; requests = []; setToken('offline-token');
  globalThis.fetch = async (url, options) => { requests.push({ url, options }); return response(200, { ok: true }); };
});

test('signup accepts an exact match and never sends confirmation or unrelated form fields', async () => {
  const payload = registrationPayload({ ...signup(), extra: 'never send' });
  await api('accounts/register/', { method: 'POST', data: payload });
  assert.deepEqual(JSON.parse(requests[0].options.body), { username: 'offline-person', password: 'Family-Test-123!', name: '가족', gender: 'female' });
});
test('signup keeps a selected reading voice without sending password confirmation', async () => {
  const payload = registrationPayload({ ...signup(), tts_voice: 'warm', extra: 'never send' });
  await api('accounts/register/', { method: 'POST', data: payload });
  assert.deepEqual(JSON.parse(requests[0].options.body), { username: 'offline-person', password: 'Family-Test-123!', name: '가족', gender: 'female', tts_voice: 'warm' });
});
test('empty, different, whitespace and stale confirmation prevent any signup request', async () => {
  for (const change of [{ confirm_password: '' }, { confirm_password: 'Other-Test-123!' }, { confirm_password: 'Family-Test-123! ' }, { password: 'Changed-Test-456!' }]) {
    await assert.rejects(async () => api('accounts/register/', { method: 'POST', data: registrationPayload({ ...signup(), ...change }) }), error => error instanceof ApiError && error.field === 'confirm_password');
  }
  assert.equal(requests.length, 0);
});
test('invalid length or missing ASCII digit is rejected before a signup request', () => {
  for (const password of ['Short-123', 'No-digits-here!', 'a'.repeat(128) + '1']) {
    assert.throws(() => registrationPayload({ ...signup(), password, confirm_password: password }), error => error.field === 'password');
  }
  assert.equal(requests.length, 0);
});
test('password whitespace is preserved when both fields match', () => {
  const password = ' Family-Test-123! ';
  assert.equal(registrationPayload({ ...signup(), password, confirm_password: password }).password, password);
});
test('HTML and empty 5xx errors show the friendly availability notice and retain login', async () => {
  for (const status of [500, 502, 503, 504]) {
    for (const html of [true, false]) {
      globalThis.fetch = async () => response(status, {}, { html });
      await assert.rejects(api('posts/'), error => error.status === status && error.unavailable && error.message === availabilityMessages.server);
      assert.equal(hasToken(), true);
    }
  }
});
test('useful JSON validation and feature errors remain actionable', async () => {
  for (const status of [400, 409, 503]) {
    globalThis.fetch = async () => response(status, { error: '사진을 확인해 주세요.' });
    await assert.rejects(api('posts/'), error => error.status === status && !error.unavailable && error.message === '사진을 확인해 주세요.');
  }
});
test('network failures and timeouts are distinguishable availability errors', async () => {
  for (const [name, expected] of [['TypeError', availabilityMessages.connection], ['AbortError', availabilityMessages.timeout]]) {
    globalThis.fetch = async () => { const error = new Error('offline'); error.name = name; throw error; };
    await assert.rejects(api('families/'), error => error.unavailable && error.message === expected);
    assert.equal(hasToken(), true);
  }
});
test('a malformed successful response is not mislabeled as an outage', async () => {
  globalThis.fetch = async () => response(200, null, { html: true });
  await assert.rejects(api('posts/'), error => error instanceof ApiError && !error.unavailable && error.message.includes('응답을 확인'));
});
test('HTML 401 still expires the current session instead of claiming maintenance', async () => {
  globalThis.fetch = async () => response(401, null, { html: true });
  await assert.rejects(api('accounts/me/'), error => error.status === 401 && !error.unavailable);
  assert.equal(hasToken(), false);
  assert.deepEqual(events, ['session-expired']);
});
test('a stale 401 cannot revoke a newer login', async () => {
  globalThis.fetch = async () => { setToken('newer-token'); return response(401, {}); };
  await assert.rejects(api('accounts/me/'));
  assert.equal(hasToken(), true);
  assert.deepEqual(events, []);
});
test('binary and multipart requests use the same outage handling with no automatic retry', async () => {
  globalThis.fetch = async (url, options) => { requests.push({ url, options }); return response(503, null, { html: true }); };
  const data = new FormData(); data.append('caption', '보관할 글');
  await assert.rejects(api('posts/', { method: 'POST', data }), error => error.unavailable);
  await assert.rejects(api('speech/', { method: 'POST', data: { text: '가족 소식' }, binary: true }), error => error.unavailable);
  assert.equal(requests.length, 2);
  assert.equal(requests[0].options.body.get('caption'), '보관할 글');
});
