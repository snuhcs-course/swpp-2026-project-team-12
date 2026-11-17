// Local browser regression checks. All API and microphone responses are synthetic.
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const types = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.png': 'image/png', '.svg': 'image/svg+xml' };
const server = http.createServer(async (req, res) => {
  try {
    const file = path.resolve(root, '.' + (req.url.split('?')[0] === '/' ? '/web/index.html' : req.url.split('?')[0]));
    if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
    res.end(await fs.readFile(file));
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
let checks = 0;
try {
  const page = await browser.newPage({ viewport: { width: 430, height: 900 } });
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  const family = { id: 77, name: '기존 가족', members: [{ id: 7, name: '민수', relationship: '나' }], invite_code: 'TEST77', digest_time: '21:00' };
  const invited = { id: 88, name: '초대받은 가족', members: [], tree: { version: 0, owner_id: '1', people: [
    { id: '1', name: '준하', gender: 'male', generation: 0, user_id: 1 },
  ], parents: [], partnerships: [] } };
  let transcriptions = 0;
  let deferTranscription = false, nextDeferred;
  await page.addInitScript(() => {
    sessionStorage.setItem('talkdock.web.token', 'synthetic-he-token');
    Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } });
    window.__heRecorders = [];
    window.MediaRecorder = class {
      constructor() { window.__heRecorders.push(this); }
      static isTypeSupported() { return true; }
      state = 'inactive';
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['test audio'], { type: 'audio/webm' }) });
        window.__heStopTask = this.onstop?.();
      }
    };
  });
  await page.route('**/api/**', async route => {
    const req = route.request(), pathname = new URL(req.url()).pathname;
    requests.push({ path: pathname, method: req.method(), room: req.headers()['x-family-room'] });
    let data;
    if (pathname === '/api/accounts/me/') data = { user_id: 7, username: 'he-user', name: '민수', gender: 'male' };
    else if (pathname === '/api/families/') data = { rooms: [family] };
    else if (pathname === '/api/families/current/') data = family;
    else if (pathname === '/api/families/lookup/') data = invited;
    else if (pathname === '/api/posts/') data = { posts: [] };
    else if (pathname === '/api/speech/voices/') data = { voices: [] };
    else if (pathname === '/api/speech/transcribe/') {
      transcriptions++;
      if (deferTranscription) { nextDeferred(route); return; }
      if (transcriptions === 1) {
        await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: '짧게 다시 말해 주세요.' }) });
        return;
      }
      data = { recognized: '오늘 산책했어요.' };
    } else { await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' }); return; }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) });
  });
  const base = `http://127.0.0.1:${server.address().port}`;
  await page.goto(base + '/#/rooms');
  const lookup = page.locator('[data-form="lookup-room"]');
  await lookup.locator('[name="invite_code"]').fill('JOIN88');
  await lookup.locator('[name="password"]').fill('room-password');
  await lookup.locator('[type="submit"]').click();
  await page.locator('[data-tree-add]').waitFor();
  const ownerPosition = () => page.locator('[data-tree-index="0"]').evaluate(button => {
    const rect = button.getBoundingClientRect(), viewport = button.closest('svg').getBoundingClientRect();
    return { x: rect.x - viewport.x, y: rect.y - viewport.y };
  });
  for (let index = 0; index < 10; index++) {
    const before = await ownerPosition();
    await page.locator('[data-tree-relation]').selectOption({ label: `자녀 추가 · ${index}/10` });
    await page.locator('[data-tree-add]').click();
    await page.waitForFunction(count => document.querySelectorAll('[data-tree-index]').length === count, index + 2);
    const after = await ownerPosition();
    assert.ok(Math.abs(after.x - before.x) < 1 && Math.abs(after.y - before.y) < 1, 'An addition must preserve the visible owner position');
    checks++;
  }
  assert.equal(await page.locator('[data-tree-relation] option').filter({ hasText: '자녀 추가' }).count(), 0); checks++;
  assert.equal(await page.locator('.tree-add-node').count(), 0); checks++;
  const beforeParent = await ownerPosition();
  await page.locator('[data-tree-relation]').selectOption({ label: '아버지 추가' });
  await page.locator('[data-tree-add]').click();
  const afterParent = await ownerPosition();
  assert.ok(Math.abs(afterParent.x - beforeParent.x) < 1 && Math.abs(afterParent.y - beforeParent.y) < 1); checks++;
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  const next = await page.locator('[data-form="join-room"] [type="submit"]').boundingBox();
  assert.ok(next && next.y >= 0 && next.y + next.height <= 900); checks++;

  await page.goto(base + '/#/feed');
  await page.locator('[data-action="compose"]').first().click();
  await page.locator('#post-caption').fill('가족 여러분 안녕하세요.');
  await page.locator('#photo-input').setInputFiles({ name: 'family.png', mimeType: 'image/png', buffer: await fs.readFile(path.join(root, 'web/assets/assistant_character.png')) });
  await page.locator('[data-action="record-post"]').first().click();
  await page.locator('[data-action="finish-record"]').click();
  await page.locator('#voice-panel strong').filter({ hasText: '다시 말해 주세요' }).waitFor(); checks++;
  assert.equal(await page.locator('#post-caption').inputValue(), '가족 여러분 안녕하세요.'); checks++;
  await page.locator('#voice-panel [data-action="record-post"]').click();
  await page.locator('[data-action="finish-record"]').click();
  await page.locator('[data-post-voice]').fill('오늘 함께 산책했어요.');
  await page.locator('#post-caption').fill('가'.repeat(1999));
  await page.locator('[data-action="post-voice-insert"]').click();
  assert.equal((await page.locator('#post-caption').inputValue()).length, 1999); checks++;
  assert.equal(await page.locator('[data-post-voice]').count(), 1); checks++;
  await page.locator('#post-caption').fill('가족 여러분 안녕하세요.');
  await page.locator('[data-action="post-voice-insert"]').click();
  assert.equal(await page.locator('#post-caption').inputValue(), '가족 여러분 안녕하세요.\n오늘 함께 산책했어요.'); checks++;
  assert.equal(await page.locator('#photo-previews .preview').count(), 1); checks++;
  assert.ok(requests.filter(request => request.path === '/api/speech/transcribe/').every(request => request.room === '77')); checks++;
  // Reproduce a previous response arriving while the next microphone session is active.
  deferTranscription = true;
  const finishDeferred = async () => {
    const pending = new Promise(resolve => { nextDeferred = resolve; });
    await page.locator('[data-action="finish-record"]').click();
    return pending;
  };
  for (const status of [200, 400]) {
    await page.locator('[data-action="record-post"]').first().click();
    const oldRequest = await finishDeferred();
    await page.locator('[data-action="record-post"]').first().click();
    assert.equal(await page.evaluate(() => window.__heRecorders.filter(item => item.state === 'recording').length), 1); checks++;
    await oldRequest.fulfill({ status, contentType: 'application/json', body: JSON.stringify(status === 200 ? { recognized: '이전 녹음' } : { error: '이전 녹음 오류' }) });
    await page.evaluate(() => window.__heStopTask);
    assert.equal(await page.locator('[data-action="finish-record"]').count(), 1, 'A stale transcript/error must not replace the new recording controls'); checks++;
    assert.equal(await page.locator('[data-action="cancel-record"]').count(), 1); checks++;
    assert.equal(await page.locator('[data-post-voice]').count(), 0); checks++;
    const newRequest = await finishDeferred();
    await newRequest.fulfill({ contentType: 'application/json', body: JSON.stringify({ recognized: '새 녹음' }) });
    await page.evaluate(() => window.__heStopTask);
    assert.equal(await page.locator('[data-post-voice]').inputValue(), '새 녹음'); checks++;
  }
  await page.locator('[data-action="record-post"]').first().click();
  const cancelledRequest = await finishDeferred();
  await page.locator('[data-action="record-post"]').first().click();
  await page.locator('[data-action="cancel-record"]').click();
  await cancelledRequest.fulfill({ contentType: 'application/json', body: JSON.stringify({ recognized: '취소한 녹음' }) });
  await page.evaluate(() => window.__heStopTask);
  assert.equal(await page.locator('#voice-panel').textContent(), ''); checks++;
  assert.equal(await page.evaluate(() => window.__heRecorders.filter(item => item.state === 'recording').length), 0); checks++;
  assert.ok(!requests.some(request => request.path === '/api/posts/' && request.method === 'POST')); checks++;
  assert.deepEqual(errors, []); checks++;
  console.log(JSON.stringify({ checks, errors }));
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
