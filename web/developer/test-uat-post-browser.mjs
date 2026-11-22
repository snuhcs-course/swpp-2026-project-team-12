// Browser integration checks with synthetic family data and intercepted API calls.
// PLAYWRIGHT_MODULE may point to an existing Playwright installation.
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const output = process.env.UAT_QA_DIR || '/tmp/talkdock-uat-post-qa'; await fs.mkdir(output, { recursive: true });
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
const errors = [], calls = []; let releaseSummary, releaseSpeech;
let delaySummary = false, delaySpeech = false, failSend = true, checks = 0;
const ok = (condition, message) => { assert.ok(condition, message); checks++; };
page.on('pageerror', error => errors.push(error.message));
const day = '2026-11-17', user = { user_id:7,username:'test',name:'정순',gender:'female' };
const family = {id:77,name:'우리 가족',members:[{id:7,name:'정순',relationship:'할머니'}],invite_code:'TEST77',digest_time:'09:00'};
const comments = Array.from({length:25},(_, i)=>({id:i+1,author_name:'준하',relationship:'손자',text:`가족의 댓글 ${i}`,created_at:`${day}T09:00:00+09:00`}));
const posts = Array.from({length:8},(_,i)=>({id:i+1,author_id:1,author_name:'준하',relationship:'손자',caption:'산책하고 집에 왔어요. '.repeat(10),images:[],comment_count:25,created_at:`${day}T10:00:00+09:00`}));
await page.addInitScript(() => {
  sessionStorage.setItem('talkdock.web.token','test-token');
  localStorage.setItem('talkdock.web.help:v2:7','true'); localStorage.setItem('talkdock.web.help:v2:7:reply:77','true');
  window.playCount=0; window.micCount=0;
  window.Audio = class { paused=true; addEventListener(){} pause(){this.paused=true;} async play(){this.paused=false;window.playCount++;} };
  Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async()=>{window.micCount++;return {getTracks:()=>[{stop(){}}]};}});
  window.MediaRecorder = class {
    static isTypeSupported(){return true;} state='inactive';
    start(){this.state='recording';} stop(){this.state='inactive';this.ondataavailable?.({data:new Blob(['synthetic recording'])}); this.onstop?.();}
  };
});
await page.route('**/api/**', async route => {
  const request=route.request(), pathname=new URL(request.url()).pathname; calls.push({path:pathname,method:request.method()});
  const reply=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  if(pathname==='/api/accounts/me/')return reply(user);
  if(pathname==='/api/families/')return reply({rooms:[family]});
  if(pathname==='/api/families/current/')return reply(family);
  if(pathname==='/api/posts/')return reply({posts});
  if(/^\/api\/posts\/\d+\/$/.test(pathname))return reply({...posts.find(p=>p.id===Number(pathname.split('/')[3])),comments});
  if(pathname.endsWith('/comments/')) {
    if(failSend)return reply({error:'보내지 못했어요. 다시 시도해 주세요.'},400);
    const comment={...comments[0],id:26,text:request.postDataJSON().text};comments.push(comment);return reply(comment,201);
  }
  if(pathname.endsWith('/message/')) { if(delaySummary)await new Promise(r=>releaseSummary=r); return reply({status:'ready',text:'준하가 산책하고 집에 왔어요.'}); }
  if(pathname==='/api/speech/') { if(delaySpeech)await new Promise(r=>releaseSpeech=r); return route.fulfill({contentType:'audio/mpeg',body:'test audio'}); }
  if(pathname.endsWith('/transcribe/'))return reply({recognized:'잘 먹었어'});
  if(pathname.endsWith('/prepare/'))return reply({id:55,converted:'잘 먹었어'});
  if(pathname==='/api/replies/55/send/')return reply({id:27},201);
  if(pathname==='/api/speech/voices/')return reply({voices:[]});
  if(pathname==='/api/daily-questions/today/')return reply({});
  return reply({error:'Unmocked '+pathname},404);
});
const waitUntil=async(predicate)=>{for(let i=0;i<100;i++){if(predicate())return;await new Promise(r=>setTimeout(r,20));}throw Error('Condition timed out');};
const close=()=>page.getByRole('button',{name:'닫기',exact:true}).click();
const assertLayout=async()=>{
  await page.locator('.post-reply-footer').waitFor();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const layout=await page.evaluate(()=>{
    const scroll=document.querySelector('.post-scroll'),footer=document.querySelector('.post-reply-footer'),send=footer.querySelector('[type=submit]');
    return {scrollBottom:scroll.getBoundingClientRect().bottom,footerTop:footer.getBoundingClientRect().top,sendBottom:send.getBoundingClientRect().bottom,height:innerHeight,scrolls:scroll.scrollHeight>scroll.clientHeight};
  });
  ok(layout.scrolls,'long history has its own scroll area');
  ok(layout.scrollBottom<=layout.footerTop+1,'history does not overlap composer');
  ok(layout.sendBottom<=layout.height,`send stays visible in a reduced viewport: ${JSON.stringify(layout)}`);
};
try {
  await page.goto(`http://127.0.0.1:${server.address().port}/#/feed`);
  await page.locator('#feed-list .post-card').first().waitFor();
  await page.locator('[data-action=feed-comments]').first().click();
  await page.locator('#comment-text').fill('남아 있어야 하는 댓글');
  await page.setViewportSize({width:430,height:550}); await assertLayout();
  await page.locator('[data-form=comment] [type=submit]').click();
  await page.getByText('보내지 못했어요. 다시 시도해 주세요.',{exact:true}).waitFor();
  ok(await page.locator('#comment-text').inputValue()==='남아 있어야 하는 댓글','failed comment keeps draft');
  await page.screenshot({path:path.join(output,'web-comment-sheet.png')});
  failSend=false;await page.locator('[data-form=comment] [type=submit]').click();
  await page.waitForFunction(()=>document.querySelector('#comment-text').value==='');checks++;
  await close(); await page.setViewportSize({width:430,height:900});
  // The composer closes back to the same DOM and reading position, without refetching the feed.
  await page.locator('#feed-list .post-card').nth(3).scrollIntoViewIfNeeded();
  const scroll=await page.evaluate(()=>scrollY), reads=calls.filter(c=>c.path==='/api/posts/').length;
  await page.locator('[data-action=compose]').first().evaluate(el=>el.click()); await close();
  ok(await page.evaluate(()=>scrollY)===scroll,'composer dismissal retains feed position');
  ok(calls.filter(c=>c.path==='/api/posts/').length===reads,'composer dismissal needs no new feed request');
  delaySummary=true;
  await page.locator('[data-action=feed-listen]').first().click();await waitUntil(()=>releaseSummary);
  ok(!await page.locator('#busy-indicator').isVisible(),'cancel remains accessible without loading overlay');
  await page.locator('.feed-audio-summary [data-action=stop-audio]').click();releaseSummary();await page.waitForTimeout(150);
  ok(await page.evaluate(()=>window.playCount)===0,'cancelled summary never autoplays');
  ok(!calls.some(c=>c.path==='/api/speech/'),'cancelled summary does not request speech');
  delaySummary=false;delaySpeech=true;
  await page.locator('[data-action=feed-listen]').first().click();await waitUntil(()=>releaseSpeech);
  await page.locator('.feed-audio-summary [data-action=stop-audio]').click();releaseSpeech();await page.waitForTimeout(150);
  ok(await page.evaluate(()=>window.playCount)===0,'cancelled TTS never autoplays');
  delaySpeech=false;
  await page.locator('[data-action=feed-listen]').first().click(); await page.waitForFunction(()=>window.playCount===1);
  await page.locator('.feed-audio-summary [data-action=stop-audio]').click();
  ok(await page.locator('[data-action=feed-stop-listen]').count()===0,'inline stop resets feed control');
  await page.locator('[data-action=feed-listen]').first().click();await page.waitForFunction(()=>window.playCount===2);
  await page.locator('#feed-list .post-card').first().evaluate(el=>el.scrollIntoView({block:'center'}));
  await page.locator('#assistant-root .assistant-launcher').click();
  ok(await page.locator('[data-bot=listen]').innerText()==='듣기 중지','assistant menu shares the playback state');
  await page.locator('[data-bot=listen]').click();
  ok(await page.locator('[data-action=feed-stop-listen]').count()===0,'assistant stop resets the inline control');
  await page.locator('[data-action=feed-voice]').first().click();
  ok(await page.evaluate(()=>window.micCount)===0,'opening voice reply does not request microphone');
  await page.locator('#voice-panel [data-action=record]').click();
  await page.locator('[data-action=finish-record]').waitFor();ok(await page.evaluate(()=>window.micCount)===1,'explicit start opens microphone once');
  await page.locator('[data-action=finish-record]').click();await page.locator('[data-form=voice-prepare] [type=submit]').click();
  await page.locator('[data-action=reply-rerecord]').click();
  ok(await page.evaluate(()=>window.micCount)===1,'rerecord returns idle');
  ok(!calls.some(c=>c.path.endsWith('/send/')),'review does not send automatically');
  await close();
  await page.locator('a[aria-label="설정으로 이동"]').click();await page.getByRole('button',{name:'어르신 화면',exact:true}).click();await page.locator('.topbar .brand').click();
  // Elderly mode: replying stays inside the card, with no dialog in between.
  const elderCard=page.locator('#feed-list .post-card').first();
  await elderCard.locator('[data-action=elder-comment]').first().click();
  await elderCard.locator('.elder-reply').waitFor();
  ok(await page.locator('dialog[open]').count()===0,'elderly comment opens inside the card');
  await page.screenshot({path:path.join(output,'web-elder-inline-reply.png')});
  await elderCard.locator('[data-action=elder-reply-record]').click();
  await elderCard.locator('[data-action=finish-record]').waitFor();
  await elderCard.locator('[data-action=finish-record]').click();
  await elderCard.locator('[data-action=elder-reply-send]').waitFor();
  ok(await elderCard.locator('.voice-draft').innerText()==='잘 먹었어','spoken reply is shown for confirmation');
  ok(!calls.some(c=>c.path.endsWith('/send/')),'elderly spoken reply waits for an explicit send');
  await elderCard.locator('[data-action=elder-reply-send]').click();
  await page.waitForFunction(()=>!document.querySelector('#feed-list .elder-reply'));
  ok(calls.some(c=>c.path==='/api/replies/55/send/'&&c.method==='POST'),'elderly spoken reply is sent from the card');
  ok(await page.locator('dialog[open]').count()===0,'sending keeps the feed in place');
  await elderCard.locator('[data-action=elder-comment]').first().click();await elderCard.locator('.elder-reply').waitFor();
  await elderCard.locator('[data-action=feed-listen]').click();
  await page.waitForFunction(()=>!document.querySelector('#feed-list .elder-reply'));
  ok(true,'listening closes an open reply area');
  await elderCard.locator('.feed-audio-summary p').waitFor();
  ok(await elderCard.locator('[data-action=elder-comment]').count()===1,'listening does not repeat the reply button');
  await elderCard.locator('.feed-ask [data-action=post-ask]').waitFor();
  ok(await elderCard.locator('.feed-ask-hint').innerText()==='이 소식 관련해서 궁금한 점을 토닥이에게 물어보세요!','listening invites a question to Todak');
  await elderCard.locator('.post-actions [data-action=elder-comment]').click();
  await elderCard.locator('.elder-reply textarea').fill('산책 잘 했구나');
  failSend=false;
  await elderCard.locator('[data-form=elder-reply] [type=submit]').click();
  await page.waitForFunction(()=>!document.querySelector('#feed-list .elder-reply'));
  await elderCard.getByText('산책 잘 했구나',{exact:true}).waitFor();
  ok(await page.locator('dialog[open]').count()===0,'typed elderly reply is sent from the card');
  // The elderly screen has no assistant; its post dialog opens from a photo tap, and these posts are text-only,
  // so send the same open-post action a photo would.
  await page.evaluate(()=>{const b=document.createElement('button');b.dataset.action='open-post';b.dataset.id='1';document.querySelector('#feed-list').append(b);b.click();b.remove();});
  await page.locator('[data-action=summary-audio]').waitFor();
  await page.setViewportSize({width:430,height:650});await assertLayout();
  await page.screenshot({path:path.join(output,'web-elder-comment.png')});
  const playsBeforeDetail=await page.evaluate(()=>window.playCount);
  delaySummary=true;releaseSummary=null;
  await page.locator('[data-action=summary-audio]').click();await waitUntil(()=>releaseSummary);
  await page.locator('#modal [data-action=stop-audio]').click();releaseSummary();await page.waitForTimeout(150);
  ok(await page.evaluate(()=>window.playCount)===playsBeforeDetail,'detail summary cancellation prevents late playback');
  ok(errors.length===0,`no browser errors: ${errors}`);
  console.log(`${checks} browser checks passed`);
} finally { releaseSummary?.();releaseSpeech?.();await browser.close();server.close(); }
