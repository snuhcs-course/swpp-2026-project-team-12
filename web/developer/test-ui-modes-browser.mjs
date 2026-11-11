// Browser integration checks with synthetic family data and intercepted API calls.
// PLAYWRIGHT_MODULE may point to an existing Playwright installation.
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const output = path.join(root, 'web/.qa/ui-modes'); await fs.mkdir(output, { recursive: true });
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
const errors = [], requests = []; page.on('pageerror', e => errors.push(e.message));
const day = new Intl.DateTimeFormat('en-CA', { timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit' }).format(new Date());
const user = { user_id:7, username:'offline-test', name:'김선희', gender:'female' };
const family = { id:77, name:'화면 테스트 가족', members:[{ id:7,name:'김선희',relationship:'할머니' }], invite_code:'TEST77', digest_time:'09:00' };
const comments = [{ id:10,author_name:'김선희',relationship:'할머니',text:'좋은 하루 보내렴!',created_at:`${day}T08:00:00+09:00` }];
const posts = [1,2,3].map(id => ({ id, author_id:id, author_name:`가족${id}`, relationship:'손자', caption: id === 1 ? '커피와 빵으로 아침을 먹었어요. '.repeat(18) : `가족의 ${id}번째 소식이에요.`, created_at:`${day}T08:00:00+09:00`, images:[], comment_count:comments.length }));
posts[0].images=[{id:1,url:'/api/posts/1/images/1/'},{id:2,url:'/api/posts/1/images/2/'}];
posts[1].caption='짧은 첫째 줄\n짧은 둘째 줄\n짧은 셋째 줄';
let feedPosts = posts;
const question = { id:5,post_id:9,date:day,version:1,kind:'choice',title:'가족과 함께하고 싶은 활동은?',options:['산책','식사'],answers:[],comments:[] };
await page.addInitScript(() => sessionStorage.setItem('talkdock.web.token', 'synthetic-token'));
await page.addInitScript(() => {
  // Exercise the listen/stop UI without a speaker, real speech provider, or autoplay policy.
  window.Audio = class {
    paused = true;
    addEventListener() {}
    async play() { this.paused = false; }
    pause() { this.paused = true; }
  };
});
await page.route('**/api/**', async route => {
  const req=route.request(), url=new URL(req.url()); requests.push({ path:url.pathname,method:req.method() }); let data;
  if (/^\/api\/posts\/\d+\/images\/\d+\/$/.test(url.pathname)) {
    await route.fulfill({contentType:'image/png',body:await fs.readFile(path.join(root,'web/assets/assistant_character.png'))});return;
  }
  if(url.pathname==='/api/accounts/me/')data=user;
  else if(url.pathname==='/api/families/')data={rooms:[family]};
  else if(url.pathname==='/api/families/current/')data=family;
  else if(url.pathname==='/api/posts/')data={posts:feedPosts,daily_question:question};
  else if(/^\/api\/posts\/\d+\/comments\/$/.test(url.pathname)) { const body=req.postDataJSON();comments.push({...comments[0],id:11,text:body.text});data=comments.at(-1); }
  else if(/^\/api\/posts\/\d+\/$/.test(url.pathname))data={...posts.find(p=>p.id===Number(url.pathname.split('/')[3])),comments};
  else if(url.pathname==='/api/daily-questions/today/')data=question;
  else if(url.pathname==='/api/digests/history/')data={dates:[day]};
  else if(url.pathname==='/api/digests/')data={date:day,status:'ready',digest_time:'09:00',text:'[손자 - 가족1] 커피와 빵으로 아침을 드셨어요.\n\n[손자 - 가족2] 가족의 소식을 전하셨어요.',posts};
  else if(url.pathname==='/api/speech/voices/')data={voices:[]};
  else if(/^\/api\/posts\/\d+\/message\/$/.test(url.pathname))data={status:'ready',text:'테스트 소식이에요.'};
  else if(url.pathname==='/api/speech/') { await route.fulfill({contentType:'audio/mpeg',body:Buffer.from([0])});return; }
  else { await route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'Unmocked route: '+url.pathname})}); return; }
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});
const launcherLook = () => page.locator('#assistant-root .assistant-launcher').evaluate(el => {const css=getComputedStyle(el);return {width:el.offsetWidth,height:el.offsetHeight,border:css.border,borderRadius:css.borderRadius,background:css.backgroundColor,imageWidth:getComputedStyle(el.querySelector('img')).width};});
let checks=0;const ok=(value,message)=>{assert.ok(value,message);checks++};
try {
  await page.goto(`http://127.0.0.1:${server.address().port}/#/feed`);
  await page.locator('#feed-list .post-card').first().waitFor();
  ok(await page.locator('.screen-bottom [data-nav]').count()===3,'standard has three tabs');
  await page.locator('#assistant-root .assistant-launcher').waitFor({state:'visible'});
  const standardLauncherLook=await launcherLook();
  ok(await page.locator('#assistant-root .assistant-launcher-label').isHidden(),'standard assistant has no visible caption');
  await page.locator('#feed-list img.loaded').first().waitFor();
  await page.screenshot({path:path.join(output,'standard.png'),fullPage:false});
  ok(await page.locator('#feed-filter, #author-filter').count()===0,'feed has no search or family filters');
  ok(await page.locator('#feed-list .post-actions').first().evaluate(el=>[...el.querySelectorAll('button')].every(button=>[...button.childNodes].every(node=>node.nodeType===3 ? !node.textContent.trim() : node.matches('svg, .sr-only')))),'standard actions use icons with accessible labels only');
  const firstCaption=page.locator('#feed-list .post-caption').first();
  ok(await firstCaption.evaluate(el=>getComputedStyle(el).webkitLineClamp==='2'&&el.clientHeight<=parseFloat(getComputedStyle(el).lineHeight)*2+1),'standard text is capped at two rendered lines');
  await page.locator('#feed-list [data-post-id="2"] [data-action="expand-post"]').waitFor();
  ok(await page.locator('#feed-list [data-post-id="3"] [data-action="expand-post"]').isHidden(),'short single-line text has no more button');
  await page.locator('#feed-list [data-action="expand-post"]').first().click();
  ok(await firstCaption.evaluate(el=>!el.classList.contains('caption-clamped')),'long caption expands');
  await page.locator('[data-action=feed-listen]').first().click();
  await page.getByRole('button',{name:'듣기 중지',exact:true}).waitFor();
  ok(await page.locator('[data-action=feed-stop-listen]').count()===1,'listen button exposes stop after loading');
  await page.locator('[data-action=feed-stop-listen]').click();
  ok(await page.locator('[data-action=feed-stop-listen]').count()===0,'stop restores the listen action');
  await page.locator('[data-action=feed-comments]').nth(1).click();
  const readingPosition=await page.evaluate(()=>scrollY);
  await page.locator('#comment-text').fill('테스트 댓글이에요.');
  await page.locator('[data-form=comment] [type=submit]').click();
  await page.locator('#comments').getByText('테스트 댓글이에요.').waitFor();
  ok(await page.locator('#modal').evaluate(el=>el.classList.contains('comments-only')),'standard comments use a sheet');
  await page.getByRole('button',{name:'닫기',exact:true}).click();
  ok(Math.abs(await page.evaluate(()=>scrollY)-readingPosition)<2,'comment completion preserves feed position');
  await page.locator('.screen-bottom [data-nav=digest]').click();
  await page.locator('.month-day').first().waitFor();
  ok(await page.locator('.month-day').count()>=28,'month calendar rendered');
  await page.getByRole('button',{name:'오늘 이야기 보기',exact:true}).click();
  ok(await page.locator('.day-story-dialog .digest-text').isVisible(),'story opens after calendar preview');
  await page.getByRole('button',{name:'닫기',exact:true}).click();
  feedPosts = [];
  await page.locator('a[aria-label="설정으로 이동"]').click();
  await page.getByRole('button',{name:'어르신 화면',exact:true}).click();
  await page.locator('.topbar .brand').click();
  await page.locator('.guided-help').waitFor();
  ok(await page.locator('.guided-help').isVisible(),'elder first use opens practice');
  const writesBefore=requests.filter(r=>r.method!=='GET').length;
  await page.locator('[data-help=next]').click();
  const feed=page.locator('.help-feed');await feed.hover({position:{x:40,y:70}});await page.mouse.wheel(0,220);await page.waitForTimeout(100);await page.mouse.wheel(0,-80);
  await page.getByText('사용 안내 3 / 6',{exact:true}).waitFor();
  await page.getByRole('button',{name:'소식 쓰기',exact:true}).last().click();
  await page.locator('[data-help=photo]').click();
  await page.locator('.help-practice [type=submit]').click();
  await page.getByText('연습 소식을 올렸어요.',{exact:true}).waitFor();
  await page.locator('[data-help=next]').click();
  await page.locator('[data-help=bot]').click();
  await page.locator('[data-help=listen]').click();
  await page.locator('[data-help=next]').click();
  await page.locator('[data-help=bot]').click();await page.locator('[data-help=day]').click();
  await page.locator('[data-help=next]').click();await page.locator('[data-help=next]').click();
  // A room with only the viewer's post must also keep the reply lesson pending.
  feedPosts = [{ ...posts[0], author_id:user.user_id }];
  await page.reload();
  await page.locator('#feed-list .post-card').waitFor();
  ok(await page.locator('.guided-help').count()===0,'own post does not trigger reply practice');
  feedPosts = posts;
  await page.getByText('가족 소식에 답장해 봐요.',{exact:true}).waitFor({timeout:35000});
  assert.equal(await page.locator('.help-caption').textContent(),posts[0].caption);
  await page.locator('[data-help=comment]').click();
  await page.locator('[data-help=voice]').click();
  ok(await page.locator('.help-comment').inputValue()==='좋은 하루 보내세요!','voice example awaits confirmation');
  await page.locator('.help-practice [type=submit]').click();
  await page.locator('[data-help=next]').click();await page.locator('[data-help=next]').click();
  await page.reload();
  await page.locator('#feed-list .post-card').first().waitFor();
  ok(await page.locator('.guided-help').count()===0,'reply practice appears only once');
  ok(requests.filter(r=>r.method!=='GET').length===writesBefore,'help never writes real posts or comments');
  ok(await page.locator('.screen-bottom [data-action=compose]').count()===1,'elder has one bottom compose action');
  ok(await page.locator('.vertical-feed [data-action=compose]').count()===0,'no duplicate elder compose button');
  ok(await page.locator('.caption-clamped').count()===0,'elder captions stay expanded');
  await page.locator('#feed-list .post-card').first().scrollIntoViewIfNeeded();
  await page.locator('[data-comments="1"]').getByText('좋은 하루 보내렴!').waitFor();
  ok(await page.locator('[data-comments="1"] .comment').count()>0,'elder comments visible inline');
  const bounds=await page.locator('.assistant-launcher').boundingBox();
  ok(bounds.x+bounds.width>=page.viewportSize().width-20,'elder assistant docks right');
  assert.deepEqual(await launcherLook(), standardLauncherLook, 'elder assistant matches the standard icon appearance'); checks++;
  const label=page.locator('#assistant-root .assistant-launcher-label');
  ok(await label.isVisible() && await label.innerText()==='토닥 도우미','elder assistant shows its label');
  const labelBounds=await label.boundingBox(), bottom=await page.locator('.screen-bottom').boundingBox();
  ok(labelBounds.y>=bounds.y+bounds.height && labelBounds.y+labelBounds.height<bottom.y,'assistant caption sits below the icon and above navigation');
  await page.locator('.screen-bottom [data-action=compose]').click();
  ok(await page.locator('[data-form=post]').isVisible(),'bottom compose opens real composer');
  await page.getByRole('button',{name:'닫기',exact:true}).click();
  await page.locator('#posting-success').waitFor({state:'hidden'});
  await page.screenshot({path:path.join(output,'elder.png'),fullPage:false});
  await page.locator('.assistant-launcher').click();
  ok(await page.getByRole('dialog',{name:'토닥 도우미 메뉴'}).isVisible(),'bot opens contextual menu');
  await page.locator('[data-bot=help]').click();await page.locator('[data-help=skip]').click();
  await page.setViewportSize({width:340,height:800});
  ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'narrow layout has no horizontal overflow');
  ok(errors.length===0,JSON.stringify(errors));
  console.log(JSON.stringify({checks,errors}));
  await fs.writeFile(path.join(output,'verification.json'),JSON.stringify({checks,errors,requests},null,2));
} catch (error) {
  await page.screenshot({path:path.join(output,'failure.png'),fullPage:false});
  console.error(JSON.stringify({checks,errors}));throw error;
} finally { await browser.close();await new Promise(resolve=>server.close(resolve)); }
