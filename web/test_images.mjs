// Run with node --test web/test_images.mjs; no browser or external service needed.
import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

globalThis.sessionStorage = { getItem: () => '', setItem() {}, removeItem() {} };
globalThis.window = { location: { origin: 'https://web.example' } };
const { imageURL, clearImages, setToken } = await import('./assets/api.js');
let requests;

beforeEach(() => {
  clearImages();
  setToken('offline-token');
  requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, blob: async () => new Blob(['jpeg-bytes'], { type: 'image/jpeg' }) };
  };
});

test('every ordered photo URL uses the local authenticated API despite PUBLIC_ORIGIN', async () => {
  for (let index = 0; index < 5; index++) {
    const url = await imageURL(`https://android.example/api/posts/12/images/${index}/`);
    assert.ok(url.startsWith('blob:'));
  }
  assert.deepEqual(requests.map(request => request.url),
    Array.from({ length: 5 }, (_, index) => `/api/posts/12/images/${index}/`));
  assert.ok(requests.every(request => request.options.headers.Authorization === 'Bearer offline-token'));
});

test('cover alias and cached indexed photos remain usable after session cache reset', async () => {
  await imageURL('/api/posts/12/image/');
  const first = await imageURL('/api/posts/12/images/0/');
  assert.equal(await imageURL('/api/posts/12/images/0/'), first);
  assert.equal(requests.length, 2);
  clearImages();
  setToken('other-account');
  await imageURL('/api/posts/12/images/0/');
  assert.equal(requests.length, 3);
  assert.equal(requests[2].options.headers.Authorization, 'Bearer other-account');
});

test('invalid photo paths never send an authenticated request', async () => {
  for (const path of ['/api/accounts/me/', '/api/posts/12/photos/100/',
                       '/api/posts/12/images/-1/', '/media/private.jpg']) {
    await assert.rejects(imageURL(path));
  }
  assert.equal(requests.length, 0);
});
