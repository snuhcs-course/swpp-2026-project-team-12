// Browser integration checks with synthetic family data and intercepted API calls.
// PLAYWRIGHT_MODULE may point to an existing Playwright installation.
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const output = process.env.UAT_QA_DIR || '/tmp/talkdock-uat-account-qa'; await fs.mkdir(output, { recursive: true });
const types = { '.js':'text/javascript', '.css':'text/css', '.html':'text/html', '.png':'image/png', '.svg':'image/svg+xml', '.gif':'image/gif' };
const server = http.createServer(async (req, res) => {
  try { const file = path.resolve(root, '.' + (req.url.split('?')[0] === '/' ? '/web/index.html' : req.url.split('?')[0]));
    if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
    const data = await fs.readFile(file); res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' }); res.end(data);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const page = await browser.newPage({ viewport: { width: 430, height: 900 } });
const errors = [], calls = []; page.on('pageerror', error => errors.push(error.message));
const user = { user_id:7, username:'test-user',name:'정순',gender:'female',token:'test-token' };
const tree = { version:1, owner_id:'1', people:[{id:'1',name:'준하',gender:'male',generation:0,user_id:1}],parents:[],partnerships:[] };
let rejectSignup = true, releaseSample;
await page.addInitScript(() => {
  window.played = []; window.Audio = class {
    constructor(url) { this.url = url; } addEventListener() {} pause() {}
    async play() { window.played.push(await (await fetch(this.url)).text()); }
  };
});
await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url()), data = request.postDataJSON();
  calls.push({path:url.pathname,data});
  const reply = (body, status = 200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  if (url.pathname === '/api/speech/voices/') return reply({default:'a',voices:[{key:'a',name:'목소리 A',sample:true},{key:'b',name:'목소리 B',sample:true}]});
  if (url.pathname === '/api/speech/voices/a/sample/') { await new Promise(resolve => { releaseSample = resolve; }); return route.fulfill({body:'A',contentType:'audio/mpeg'}); }
  if (url.pathname === '/api/speech/voices/b/sample/') return route.fulfill({body:'B',contentType:'audio/mpeg'});
  if (url.pathname === '/api/accounts/register/') return rejectSignup ? reply({error:'너무 흔한 비밀번호예요. 다른 비밀번호를 만들어 주세요.',field:'password'},400) : reply(user,201);
  if (url.pathname === '/api/accounts/me/') return reply(user);
  if (url.pathname === '/api/families/') return reply({rooms:[]});
  if (url.pathname === '/api/families/lookup/') return reply({id:77,name:'우리 가족',members:[{id:1}],tree});
  return reply({});
});
try {
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.locator('[data-action="auth-register"]').click();
  await page.locator('[name="tts_voice"]').selectOption('a');
  await page.locator('[data-voice-sample]').click();
  await page.locator('[name="tts_voice"]').selectOption('b');
  await page.locator('[data-voice-sample]').click();
  await page.waitForFunction(() => window.played.includes('B'));
  releaseSample(); await page.waitForTimeout(100);
  assert.deepEqual(await page.evaluate(() => window.played), ['B']);
  await page.locator('[data-voice-sample]').click();
  await page.waitForFunction(() => window.played.length === 2);
  assert.equal(calls.filter(c => c.path === '/api/speech/voices/b/sample/').length,1);
  const form = page.locator('[data-form="register"]');
  await form.locator('[name="name"]').fill('정순'); await form.locator('[name="username"]').fill('test-user');
  await form.locator('[name="gender"]').selectOption('female');
  await form.locator('[name="password"]').fill('x7!'); await form.locator('[name="confirm_password"]').fill('x7!');
  await form.locator('[type="submit"]').click();
  await page.waitForFunction(() => document.querySelector('.field-error')?.textContent.includes('10자'));
  assert.equal(calls.filter(c => c.path === '/api/accounts/register/').length,0);
  await page.screenshot({path:path.join(output,'web-password-error.png'),fullPage:true});
  await form.locator('[name="password"]').fill('password123'); await form.locator('[name="confirm_password"]').fill('password123');
  await form.locator('[type="submit"]').click();
  await page.waitForFunction(() => document.querySelector('.field-error')?.textContent.includes('너무 흔한'));
  assert.equal(await form.locator('[name="password"]').inputValue(),'password123');
  rejectSignup = false;
  await form.locator('[name="password"]').fill('Cedar-lake-732!'); await form.locator('[name="confirm_password"]').fill('Cedar-lake-732!');
  await form.locator('[type="submit"]').click();
  const lookup = page.locator('[data-form="lookup-room"]');
  await lookup.locator('[name="invite_code"]').fill('abc123');
  assert.equal(await lookup.locator('[name="invite_code"]').inputValue(),'ABC123');
  await lookup.locator('[name="password"]').fill('family-pass'); await lookup.locator('[type="submit"]').click();
  await page.locator('#join-panel .family-tree-board').waitFor();
  assert.equal(calls.find(c => c.path === '/api/families/lookup/').data.invite_code,'ABC123');
  assert.deepEqual(errors,[]);
  console.log('PASS: preview race/cache, inline local/server password errors, uppercase code and lookup payload');
} finally { releaseSample?.(); await browser.close(); await new Promise(resolve => server.close(resolve)); }
