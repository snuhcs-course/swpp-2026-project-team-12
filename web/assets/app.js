import { api, ApiError, hasToken, setToken, imageURL, clearImages } from './api.js';
import { icon } from './icons.js';
import { FamilyTreeDraft } from './family-tree.js';
import { treeMarkup, mountTree } from './family-tree-view.js';

const app = document.querySelector('#app');
const modal = document.querySelector('#modal');
const toastBox = document.querySelector('#toast');
const busyIndicator = document.querySelector('#busy-indicator');
const pendingOperations = new Set();
const state = { user: null, room: null, posts: [], detail: null, dialogue: [], files: [], lookup: null, pageVersion: 0, modalVersion: 0, session: 0, digest: null, photoIndex: 0 };
const nav = [['feed', 'home', '가족 소식'], ['search', 'search', '추억 찾기'], ['digest', 'book', '하루 모아보기'], ['family', 'people', '우리 가족']];
let toastTimer, observer, audio, audioURL, recorder, recordingStream, recordingTimer;
let previewURLs = [];

const e = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const $ = (selector, root = document) => root.querySelector(selector);
const avatar = (name, id = 0, size = '') => `<span class="avatar tone-${Math.abs(Number(id) || 0) % 5} ${size}" aria-hidden="true">${e([...String(name || '가')][0])}</span>`;
const brand = () => '<a class="brand" href="#/feed" aria-label="토닥 홈"><img src="/web/assets/favicon.svg" alt="" width="42" height="42"><span>토닥<small>TALK DOCK</small></span></a>';
const button = (action, label, symbol, cls = 'button secondary', extra = '') => `<button type="button" class="${cls}" data-action="${action}" ${extra}>${symbol ? icon(symbol) : ''}${label}</button>`;
const loading = (text = '불러오는 중이에요') => `<div class="loading" role="status"><img class="loading-mascot" src="/web/assets/todak_joy.gif" alt="" width="140" height="140"><span>${e(text)}</span></div>`;
const errorBlock = message => `<p class="error" role="alert">${e(message)}</p>`;
const empty = (symbol, title, text, action = '') => `<div class="empty-state"><span class="empty-icon">${icon(symbol)}</span><h3>${title}</h3><p>${text}</p>${action}</div>`;
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
function dateLabel(value, full = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', ...(full ? { year: 'numeric', hour: 'numeric', minute: '2-digit' } : { weekday: 'short' }) }).format(date);
}
function toast(message) {
  clearTimeout(toastTimer);
  (modal.open ? modal : document.body).append(toastBox);
  toastBox.textContent = message;
  toastBox.hidden = false;
  toastTimer = setTimeout(() => { toastBox.hidden = true; }, 5000);
}
function field(label, name, type = 'text', attrs = '') {
  return `<label class="field"><span>${label}</span><input name="${name}" type="${type}" ${attrs}></label>`;
}
function stopAudio() {
  if (audio) { audio.pause(); audio = null; }
  if (audioURL) { URL.revokeObjectURL(audioURL); audioURL = null; }
  document.querySelectorAll('[data-action="stop-audio"]').forEach(node => { node.hidden = true; });
}
function updateBusyIndicator() {
  const active = [...pendingOperations].some(operation =>
    operation.session === state.session && operation.pageVersion === state.pageVersion &&
    (operation.modalVersion === null || (modal.open && operation.modalVersion === state.modalVersion)));
  // Native dialogs occupy the browser's top layer. Keep the loading card inside
  // the open dialog so AI and voice requests remain visible above its backdrop.
  (modal.open ? modal : document.body).append(busyIndicator);
  busyIndicator.hidden = !active;
}
function cleanupModal() {
  state.modalVersion++;
  state.detail = null;
  state.dialogue = [];
  stopRecording(true);
  stopAudio();
  previewURLs.forEach(url => URL.revokeObjectURL(url));
  previewURLs = [];
  state.files = [];
  document.body.append(toastBox);
  updateBusyIndicator();
  document.body.classList.remove('modal-open');
}
function openModal(content, className = '') {
  if (modal.open) modal.close();
  cleanupModal();
  modal.className = className;
  modal.innerHTML = content;
  modal.showModal();
  document.body.classList.add('modal-open');
}
function modalHeading(title, eyebrow = '') {
  return `<header class="modal-heading"><div>${eyebrow ? `<p class="eyebrow">${eyebrow}</p>` : ''}<h2 id="modal-title">${title}</h2></div>${button('close-modal', '<span class="sr-only">닫기</span>', 'close', 'icon-button')}</header>`;
}
modal.addEventListener('close', () => { if (!modal.open) cleanupModal(); });
modal.addEventListener('click', event => { if (event.target === modal) { const rect = modal.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) modal.close(); } });

async function busy(element, task, errorTarget) {
  if (element?.disabled) return;
  const original = element?.innerHTML;
  const session = state.session;
  const operation = { session, pageVersion: state.pageVersion, modalVersion: modal.contains(element) ? state.modalVersion : null };
  pendingOperations.add(operation);
  updateBusyIndicator();
  if (element) { element.disabled = true; element.setAttribute('aria-busy', 'true'); element.innerHTML = '<img class="loading-mascot button-mascot" src="/web/assets/todak_joy.gif" alt="" width="28" height="28"><span class="sr-only">잠시만요</span>'; }
  if (errorTarget) errorTarget.textContent = '';
  try { await task(); }
  catch (error) {
    if (session !== state.session) return;
    if (errorTarget?.isConnected) errorTarget.textContent = error.message;
    else toast(error.message || '다시 시도해 주세요.');
  } finally {
    pendingOperations.delete(operation);
    updateBusyIndicator();
    if (element?.isConnected) { element.disabled = false; element.removeAttribute('aria-busy'); element.innerHTML = original; }
  }
}

function resetSession() {
  state.session++;
  state.pageVersion++;
  state.user = state.room = state.lookup = state.digest = null;
  state.posts = [];
  setToken('');
  clearImages();
  stopAudio();
  if (modal.open) modal.close();
  observer?.disconnect();
  updateBusyIndicator();
}
window.addEventListener('session-expired', () => { resetSession(); renderAuth(); toast('로그인 시간이 만료되었어요. 다시 로그인해 주세요.'); });

function renderAuth(register = false) {
  app.innerHTML = `<main id="main" class="auth-layout">
    <section class="auth-story">${brand()}<div class="story-copy"><p class="eyebrow">마음이 닿는 곳, 토닥</p><h1>작은 일상이 모여,<br>우리의 이야기가 돼요.</h1><p>멀리 있어도 가까이.<br>사진 한 장, 따뜻한 한마디로 안부를 나눠요.</p></div>
      <div class="story-art" aria-hidden="true"><div class="art-sun"></div><div class="art-window"><div class="art-hill"></div><div class="art-hill second"></div><span class="art-heart">${icon('heart')}</span></div><div class="art-note">${icon('leaf')}오늘도, 함께라서 좋은 날</div><div class="art-stamp">우리 가족의<br>소중한 순간들</div></div>
      <p class="story-foot">일상을 나누고, 마음을 잇습니다.</p></section>
    <section class="auth-panel"><div class="auth-form-wrap"><span class="tag">우리 가족만의 공간</span><h2>${register ? '반가워요, 처음 오셨나요?' : '다시 만나서 반가워요'}</h2><p class="muted">${register ? '계정을 만들고 가족의 이야기를 함께 시작해요.' : '가족의 새로운 이야기가 기다리고 있어요.'}</p>
      <div class="segmented" aria-label="계정 메뉴"><button type="button" data-action="auth-login" class="${register ? '' : 'selected'}" aria-pressed="${!register}">로그인</button><button type="button" data-action="auth-register" class="${register ? 'selected' : ''}" aria-pressed="${register}">회원가입</button></div>
      <form data-form="${register ? 'register' : 'login'}">
        ${register ? field('이름', 'name', 'text', 'required maxlength="40" autocomplete="name" placeholder="가족에게 보여줄 이름"') : ''}
        ${field('아이디', 'username', 'text', 'required maxlength="150" autocomplete="username" placeholder="아이디를 입력해 주세요" autocapitalize="none"')}
        ${field('비밀번호', 'password', 'password', `required maxlength="128" ${register ? 'minlength="10"' : ''} autocomplete="${register ? 'new-password' : 'current-password'}" placeholder="${register ? '숫자를 포함한 10자 이상' : '비밀번호를 입력해 주세요'}"`)}
        ${register ? '<label class="field"><span>가족 관계 표시에 사용할 성별</span><select name="gender" required><option value="">성별을 선택해 주세요</option><option value="female">여성</option><option value="male">남성</option></select></label><p class="help">비밀번호는 숫자를 포함해 10자 이상으로 만들어 주세요. 아이디·이름과 비슷하거나 흔한 값, 숫자만으로는 만들 수 없어요.</p>' : ''}
        <p class="form-error" role="alert"></p><button class="button primary full" type="submit">${register ? '계정 만들기' : '우리 가족 만나러 가기'}${icon('arrow')}</button>
      </form><p class="auth-hint">${icon('heart')}안드로이드에서 쓰던 계정으로도 로그인할 수 있어요.</p></div></section></main>`;
}

async function enterApp() {
  const session = state.session;
  state.user = await api('accounts/me/');
  if (session !== state.session) return;
  try { state.room = await api('families/current/'); }
  catch (error) { if (error.status !== 403) throw error; state.room = null; }
  if (session !== state.session) return;
  if (!state.room) return renderOnboarding();
  renderShell();
  await renderPage();
}

function renderOnboarding() {
  app.innerHTML = `<main id="main" class="onboarding"><header>${brand()}${button('logout', '로그아웃', 'logout', 'button quiet')}</header>
    <div class="onboarding-intro"><p class="eyebrow">우리 가족, 여기서 만나요</p><h1>${e(state.user.name)}님, 가족과 연결해 볼까요?</h1><p class="muted">새로운 가족방을 만들거나, 가족에게 받은 초대코드로 참여하세요.</p></div>
    <div class="onboarding-grid"><section class="panel"><span class="empty-icon">${icon('home')}</span><h2>가족방 만들기</h2><p class="muted">우리 가족의 첫 이야기를 시작해요.</p><form data-form="create-room">${field('가족방 이름', 'room_name', 'text', 'required maxlength="60" placeholder="예: 행복이 피어나는 우리 집"')}${field('가족방 비밀번호', 'password', 'password', 'required maxlength="128" autocomplete="new-password"')}${field('하루 요약 시간 (한국 시간)', 'digest_time', 'time', 'required value="21:00"')}<p class="form-error" role="alert"></p><button type="submit" class="button primary full">새 가족방 만들기${icon('plus')}</button></form></section>
    <section class="panel"><span class="empty-icon sage">${icon('people')}</span><h2>초대받은 가족방에 참여</h2><p class="muted">초대코드와 가족방 비밀번호를 입력해 주세요.</p><form data-form="lookup-room">${field('초대코드', 'invite_code', 'text', 'required maxlength="8" autocomplete="off" placeholder="6자리 초대코드"')}${field('가족방 비밀번호', 'password', 'password', 'required maxlength="128" autocomplete="off"')}<p class="form-error" role="alert"></p><button type="submit" class="button secondary full">가족방 확인하기${icon('arrow')}</button></form><div id="join-panel"></div></section></div></main>`;
}

function renderJoinPreview(message = '') {
  const { room, draft } = state.lookup;
  const selected = draft.people.find(person => person.id === draft.selectedId);
  const valid = draft.canClaim(draft.selectedId, state.user.gender);
  $('#join-panel').innerHTML = `<div class="join-preview"><h3>${e(room.name)}</h3><p class="muted">+로 가족을 연결하고, 가계도에서 내 빈자리를 눌러 주세요.</p>
    ${message ? errorBlock(message) : ''}${treeMarkup(draft, { editable: true, gender: state.user.gender, userId: state.user.user_id })}
    <p class="tree-selection" role="status">${valid ? `선택한 내 자리: ${e(selected.name || state.user.name)}` : '성별이 맞는 빈자리를 선택해 주세요. 가입한 가족은 선택할 수 없어요.'}</p>
    <div class="button-row">${button('undo-tree', '마지막 추가 취소', '', 'button secondary', draft.additions.length ? '' : 'disabled')}${button('reload-tree', '처음부터 다시', 'refresh', 'button quiet')}</div>
    <form data-form="join-room"><input type="hidden" name="person_id" value="${e(draft.selectedId || '')}"><p class="form-error" role="alert"></p><button type="submit" class="button primary full" ${valid ? '' : 'disabled'}>이 자리로 가족방에 참여하기${icon('arrow')}</button></form></div>`;
  mountTree($('#join-panel .family-tree-board'), draft, {
    editable: true,
    onPerson(id) { draft.selectedId = id; renderJoinPreview(); },
    onAdd(action) {
      try {
        draft.add(action.anchor_id, action.relation, action.co_parent_id);
        if (!draft.canClaim(draft.selectedId, state.user.gender)) draft.selectedId = null;
        renderJoinPreview();
      } catch (error) { renderJoinPreview(error.message); }
    },
  });
}

function renderShell() {
  app.innerHTML = `<div class="app-layout"><aside class="sidebar">${brand()}<div class="sidebar-label">우리의 이야기</div><nav aria-label="주 메뉴">${nav.map(([key, symbol, label]) => `<a href="#/${key}" data-nav="${key}">${icon(symbol)}<span>${label}</span>${icon('chevron', 'nav-chevron')}</a>`).join('')}</nav>
    <div class="sidebar-note">${icon('heart')}<p>자주 보지 못해도,<br>마음은 늘 가까이.</p><span>오늘도 안부를 전해 보세요.</span></div>
    <div class="sidebar-bottom"><a href="#/settings" data-nav="settings">${icon('settings')}계정 설정</a><button type="button" data-action="logout">${icon('logout')}로그아웃</button><div class="profile">${avatar(state.user.name, state.user.user_id)}<div><strong>${e(state.user.name)}</strong><small>@${e(state.user.username)}</small></div><span class="online-dot" title="로그인됨"></span></div></div></aside>
    <div class="workspace"><header class="topbar"><span class="room-label">${icon('home')}<span>${e(state.room.name)}</span><span class="private-badge">가족 전용</span></span><div class="topbar-actions"><span class="today-label">${dateLabel(new Date(), false)}</span>${button('text-size', '큰 글씨', 'text', 'button quiet compact', `aria-pressed="${document.documentElement.classList.contains('large-text')}"`)}</div></header><main id="main" tabindex="-1"><div id="page"></div></main><footer class="workspace-footer"><span>토닥</span>가족의 일상을 잇는 따뜻한 공간</footer></div></div>`;
  window.scrollTo(0, 0);
}
function pageHeading(eyebrow, title, text, controls = '') {
  return `<header class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="muted">${text}</p></div>${controls}</header>`;
}
function currentRoute() { const route = location.hash.replace(/^#\/?/, '').split('?')[0]; return ['feed', 'search', 'digest', 'family', 'settings'].includes(route) ? route : 'feed'; }
async function renderPage() {
  if (!state.room || !state.user) return;
  const route = currentRoute();
  const version = ++state.pageVersion;
  updateBusyIndicator();
  stopAudio();
  observer?.disconnect();
  if (modal.open) modal.close();
  document.querySelectorAll('[data-nav]').forEach(link => { const active = link.dataset.nav === route; link.classList.toggle('active', active); if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current'); });
  const page = $('#page');
  try {
    if (route === 'feed') await renderFeed(version);
    if (route === 'search') renderSearch();
    if (route === 'digest') await renderDigest(version);
    if (route === 'family') {
      page.innerHTML = loading('최신 가계도를 불러오고 있어요');
      const room = await api('families/current/');
      if (version !== state.pageVersion) return;
      state.room = room;
      renderFamily();
    }
    if (route === 'settings') renderSettings();
  } catch (error) {
    if (version === state.pageVersion) page.innerHTML = `${errorBlock(error.message)}${button('refresh-page', '다시 불러오기', 'refresh')}`;
  }
}
window.addEventListener('hashchange', () => { if (state.room) { window.scrollTo(0, 0); renderPage(); } });
document.querySelector('.skip-link').addEventListener('click', event => {
  event.preventDefault();
  const main = $('#main');
  if (main) { main.tabIndex = -1; main.focus(); }
});

function familyRail() {
  return `<aside class="right-rail"><section class="family-rail panel"><div class="rail-icon">${icon('home')}</div><p class="eyebrow">우리만의 따뜻한 공간</p><h2>${e(state.room.name)}</h2><p class="muted">${state.room.members.length}명이 함께 이야기를 나누고 있어요.</p><div class="avatar-stack">${state.room.members.slice(0, 7).map(member => avatar(member.name, member.id)).join('')}</div><a href="#/family" class="text-link">우리 가족 보기${icon('arrow')}</a><div class="invite-row"><span>가족 초대코드</span><strong>${e(state.room.invite_code)}</strong>${button('copy-code', '<span class="sr-only">초대코드 복사</span>', 'copy', 'icon-button')}</div></section>
    <section class="digest-rail"><span class="tag">하루를 마무리하며</span>${icon('book', 'rail-book')}<h3>오늘의 이야기를<br>한눈에 모아보세요.</h3><p>매일 ${e(state.room.digest_time)}, 가족의 소식을<br>따뜻한 요약으로 전해드려요.</p><a href="#/digest" class="text-link">하루 모아보기${icon('arrow')}</a></section><p class="rail-caption">${icon('leaf')}평범한 하루도, 함께라서 특별하니까.</p></aside>`;
}
async function renderFeed(version) {
  $('#page').innerHTML = `${pageHeading('OUR FAMILY, EVERY DAY', '우리 가족의 작은 일상', '오늘은 어떤 하루를 보내셨나요? 소소한 이야기를 들려주세요.', button('compose', '소식 남기기', 'plus', 'button primary'))}<div class="feed-layout"><section aria-label="가족 소식"><button type="button" data-action="compose" class="composer-prompt">${avatar(state.user.name, state.user.user_id)}<span>${e(state.user.name)}님, 오늘의 안부를 전해 보세요.</span>${icon('photo')}</button><div class="feed-toolbar"><h2>최근 소식 <span id="post-count"></span></h2>${button('refresh-feed', '<span class="sr-only">소식 새로고침</span>', 'refresh', 'icon-button')}</div><div class="feed-filter"><label class="search-field">${icon('search')}<input id="feed-filter" type="search" placeholder="불러온 소식에서 글·이름 찾기" aria-label="최근 소식 필터"></label><label class="sr-only" for="author-filter">작성자</label><select id="author-filter"><option value="">가족 전체</option>${state.room.members.map(member => `<option value="${member.id}">${e(member.name)}</option>`).join('')}</select></div><div id="feed-list">${loading('가족의 이야기를 가져오고 있어요')}</div></section>${familyRail()}</div>`;
  const result = await api('posts/');
  if (version !== state.pageVersion) return;
  state.posts = result.posts;
  updateFeed();
}
function postCard(post) {
  const photos = post.images || [];
  return `<article class="post-card"><header class="post-author">${avatar(post.author_name, post.author_id)}<div><strong>${e(post.author_name)}</strong><span class="relationship">${e(post.relationship)}</span><time datetime="${e(post.created_at)}">${dateLabel(post.created_at, true)}</time></div><span class="family-only">가족에게만</span></header>
    ${photos.length ? `<button type="button" class="post-photo" data-action="open-post" data-id="${post.id}" aria-label="${e(post.author_name)}님의 사진과 소식 보기"><img data-post="${post.id}" data-photo-url="${e(photos[0].url)}" alt="${e(post.author_name)}님이 공유한 사진" loading="lazy">${photos.length > 1 ? `<span class="photo-count">${icon('photo')}${photos.length}</span>` : ''}</button>` : ''}
    <div class="post-body"><p class="post-caption">${e(post.caption)}</p></div><footer class="post-actions">${button('open-post', `댓글 <span>${post.comment_count}</span>`, 'comment', 'button quiet', `data-id="${post.id}"`)}${button('post-summary', 'AI로 소식 읽기', 'sparkle', 'button quiet ai-link', `data-id="${post.id}"`)}</footer></article>`;
}
function updateFeed() {
  const query = ($('#feed-filter')?.value || '').trim().toLocaleLowerCase();
  const author = $('#author-filter')?.value;
  const posts = state.posts.filter(post => (!author || String(post.author_id) === author) && `${post.caption} ${post.author_name}`.toLocaleLowerCase().includes(query));
  $('#post-count').textContent = `${posts.length}`;
  $('#feed-list').innerHTML = posts.length ? posts.map(postCard).join('') : empty('heart', query || author ? '일치하는 소식이 없어요' : '첫 번째 안부를 기다리고 있어요', query || author ? '검색어나 가족을 바꿔서 다시 찾아보세요.' : '사진 한 장도, 짧은 글 한 줄도 좋아요. 가족에게 오늘을 전해 보세요.', query || author ? '' : button('compose', '첫 소식 남기기', 'plus', 'button primary'));
  hydrateImages();
}
function hydrateImages(root = document) {
  observer ||= new IntersectionObserver(entries => {
    entries.forEach(entry => { if (entry.isIntersecting) { observer.unobserve(entry.target); loadImage(entry.target); } });
  }, { rootMargin: '300px' });
  root.querySelectorAll('img[data-post]').forEach(img => observer.observe(img));
}
async function loadImage(img) {
  try { const url = await imageURL(img.dataset.photoUrl); if (img.isConnected) { img.src = url; img.classList.add('loaded'); } }
  catch { if (img.isConnected) { img.alt = '사진을 불러오지 못했어요. 소식을 다시 열어 주세요.'; img.classList.add('image-failed'); } }
}

async function openPost(id, summarize = false) {
  openModal(`${modalHeading('가족 소식')}${loading()}`, 'post-dialog');
  const version = state.modalVersion;
  try {
    const post = await api(`posts/${id}/`);
    if (version !== state.modalVersion || !modal.open) return;
    state.detail = post;
    state.photoIndex = 0;
    modal.innerHTML = `${modalHeading('소소한 하루, 다정한 이야기', 'FAMILY MOMENT')}<div class="post-detail ${post.images.length ? '' : 'text-only'}">${post.images.length ? `<section class="detail-gallery" aria-label="공유한 사진"><div id="gallery-stage"></div>${post.images.length > 1 ? `<div class="photo-thumbnails">${post.images.map((photo, index) => `<button type="button" data-action="select-photo" data-index="${index}" aria-label="${index + 1}번 사진" aria-pressed="${index === 0}"><img data-post="${post.id}" data-photo-url="${e(photo.url)}" alt="${index + 1}번 사진 미리보기"></button>`).join('')}</div>` : ''}</section>` : ''}<section class="detail-conversation"><header class="post-author">${avatar(post.author_name, post.author_id)}<div><strong>${e(post.author_name)}</strong><span class="relationship">${e(post.relationship)}</span><time datetime="${e(post.created_at)}">${dateLabel(post.created_at, true)}</time></div></header><p class="detail-caption">${e(post.caption)}</p>
      <section class="ai-panel"><div class="ai-heading">${icon('sparkle')}<h3>AI와 함께 읽어요</h3></div><p class="help">소식을 쉽게 풀어 읽고, 궁금한 점을 물어보세요.</p><div class="button-row">${button('summary', '소식 요약하기', 'sparkle', 'button secondary compact')}${button('summary-audio', '요약 듣기', 'volume', 'button quiet compact')}${button('stop-audio', '듣기 중지', 'stop', 'button quiet compact', 'hidden')}</div><div id="summary-result" class="ai-result" aria-live="polite"></div><div id="question-history" class="question-history" aria-live="polite"></div><form data-form="post-question" class="inline-form"><label class="sr-only" for="post-question">이 소식에 대해 물어보기</label><input id="post-question" name="question" maxlength="1000" required placeholder="이 소식에 대해 궁금한 점은?"><button type="submit" class="icon-button send-button" aria-label="AI에게 질문하기">${icon('arrow')}</button><p class="form-error" role="alert"></p></form><p class="fine-print">AI 답변은 실제 소식과 다를 수 있어요. 중요한 내용은 가족에게 확인해 주세요.</p></section>
      <section class="comments-section"><h3>마음을 나눠요 <span id="comment-count">${post.comments.length}</span></h3><div id="comments"></div><form data-form="comment"><label class="sr-only" for="comment-text">가족에게 댓글 남기기</label><textarea id="comment-text" name="text" required maxlength="2000" rows="2" placeholder="다정한 한마디를 남겨보세요."></textarea><p class="form-error" role="alert"></p><div class="comment-submit">${button('record', '음성으로 답장', 'mic', 'button quiet compact')}<button type="submit" class="button primary compact">댓글 보내기${icon('arrow')}</button></div></form><div id="voice-panel" aria-live="polite"></div></section></section></div>`;
    renderComments();
    if (post.images.length) showPhoto(0);
    hydrateImages(modal);
    if (summarize) await busy($('[data-action="summary"]', modal), () => loadSummary());
  } catch (error) {
    if (version === state.modalVersion) modal.innerHTML = `${modalHeading('소식을 불러오지 못했어요')}${errorBlock(error.message)}${button('retry-post', '다시 열기', 'refresh', 'button secondary', `data-id="${id}"`)}`;
  }
}
function showPhoto(index) {
  const post = state.detail;
  if (!post || !post.images[index]) return;
  state.photoIndex = index;
  $('#gallery-stage').innerHTML = `<img data-post="${post.id}" data-photo-url="${e(post.images[index].url)}" alt="${e(post.author_name)}님이 공유한 ${index + 1}번 사진"><span class="gallery-index">${index + 1} / ${post.images.length}</span>`;
  modal.querySelectorAll('[data-action="select-photo"]').forEach(node => node.setAttribute('aria-pressed', Number(node.dataset.index) === index));
  loadImage($('#gallery-stage img'));
}
function renderComments() {
  const comments = state.detail.comments;
  $('#comment-count').textContent = comments.length;
  $('#comments').innerHTML = comments.length ? comments.map(comment => `<article class="comment">${avatar(comment.author_name, comment.id, 'small')}<div><strong>${e(comment.author_name)}</strong><span class="relationship">${e(comment.relationship)}</span><p>${e(comment.text)}</p><small>${dateLabel(comment.created_at, true)}${comment.source === 'voice' ? ' · 음성으로 전한 마음' : ''}</small></div></article>`).join('') : '<p class="no-comments">아직 댓글이 없어요. 첫 번째 마음을 전해 주세요.</p>';
}
async function loadSummary() {
  const post = state.detail;
  const version = state.modalVersion;
  const result = await api(`posts/${post.id}/message/`, { method: 'POST' });
  if (version !== state.modalVersion) return;
  const target = $('#summary-result');
  if (result.status === 'ready') { post.summary = result.text; target.textContent = result.text; }
  else if (result.status === 'failed') throw new ApiError('AI 요약을 준비하지 못했어요. 잠시 후 다시 시도해 주세요.');
  else { target.textContent = '요약을 준비하고 있어요. 잠시 후 요약 버튼을 다시 눌러 주세요.'; }
}
async function playSpeech(text, target, valid = () => true) {
  if (!text) throw new ApiError('먼저 요약을 불러와 주세요.');
  stopAudio();
  const blob = await api('speech/', { method: 'POST', data: { text }, binary: true });
  if (!valid()) return;
  audioURL = URL.createObjectURL(blob);
  audio = new Audio(audioURL);
  audio.addEventListener('ended', stopAudio, { once: true });
  audio.addEventListener('error', () => { stopAudio(); toast('음성을 재생하지 못했어요. 다시 시도해 주세요.'); }, { once: true });
  try { await audio.play(); }
  catch { stopAudio(); throw new ApiError('재생이 차단되었어요. 듣기 버튼을 다시 눌러 주세요.'); }
  if (target?.isConnected) target.hidden = false;
}

function openComposer() {
  openModal(`${modalHeading('오늘의 안부를 남겨요', 'A LITTLE MOMENT')}<form data-form="post"><div class="composer-user">${avatar(state.user.name, state.user.user_id)}<div><strong>${e(state.user.name)}</strong><p class="help">${e(state.room.name)} 가족에게 공유돼요.</p></div></div><label class="sr-only" for="post-caption">소식 내용</label><textarea id="post-caption" name="caption" maxlength="2000" rows="5" placeholder="오늘 있었던 일, 가족과 나누고 싶은 순간을 들려주세요."></textarea><div class="character-count"><span id="caption-count">0</span> / 2,000</div><label class="upload-zone" id="drop-zone" tabindex="0">${icon('photo')}<strong>사진을 여기에 놓거나 클릭해 주세요</strong><span>최대 5장 · 한 장당 10MB · 전체 30MB · 사진 없이 글만 써도 좋아요</span><input id="photo-input" type="file" accept="image/jpeg,image/png,image/webp,image/gif,image/bmp" multiple class="sr-only"></label><div id="photo-previews" class="photo-previews"></div><p class="form-error" role="alert"></p><div class="composer-footer"><p class="help">${icon('heart')}작은 안부가 가족에게 큰 기쁨이 돼요.</p><button type="submit" class="button primary">소식 전하기${icon('arrow')}</button></div></form>`, 'compose-dialog');
}
function addFiles(files) {
  const next = [...state.files, ...files];
  if (next.length > 5) return toast('사진은 최대 5장까지 선택할 수 있어요.');
  if (next.some(file => !/^image\/(jpeg|png|webp|gif|bmp)$/.test(file.type))) return toast('JPG, PNG, WebP, GIF, BMP 사진을 선택해 주세요.');
  if (next.some(file => file.size > 10 * 1024 * 1024) || next.reduce((sum, file) => sum + file.size, 0) > 30 * 1024 * 1024) return toast('사진은 한 장당 10MB, 전체 30MB까지 올릴 수 있어요.');
  state.files = next;
  renderPreviews();
}
function renderPreviews() {
  previewURLs.forEach(url => URL.revokeObjectURL(url));
  previewURLs = state.files.map(file => URL.createObjectURL(file));
  $('#photo-previews').innerHTML = state.files.map((file, index) => `<div class="preview"><img src="${previewURLs[index]}" alt="${e(file.name)}"><button type="button" data-action="remove-photo" data-index="${index}" class="icon-button" aria-label="${e(file.name)} 제외">${icon('close')}</button><span>${e(file.name)}</span></div>`).join('');
}

function renderSearch() {
  $('#page').innerHTML = `${pageHeading('MEMORIES TOGETHER', '함께 쌓아온 추억 찾기', '기억이 가물가물한 순간, 가족의 이야기 속에서 함께 찾아봐요.')}<section class="search-hero panel"><span class="empty-icon sage">${icon('search')}</span><h2>우리 가족의 어떤 순간이 궁금하세요?</h2><p class="muted">가족이 남긴 소식을 바탕으로 AI가 추억을 찾아드려요.</p><form data-form="search" class="memory-search"><label class="sr-only" for="memory-question">가족 기록에서 찾을 내용</label><input id="memory-question" name="question" required maxlength="1000" placeholder="예: 지난번 가족 여행은 어디로 갔었지?"><button class="button primary" type="submit">추억 찾기${icon('arrow')}</button><p class="form-error" role="alert"></p></form><div class="suggestions">${['최근 가족 여행 이야기 찾아줘', '가족이 함께 먹은 음식이 궁금해', '생일에 있었던 일 알려줘'].map(text => button('search-suggestion', e(text), '', 'suggestion', `data-question="${e(text)}"`)).join('')}</div></section><div id="search-result" aria-live="polite"></div><p class="page-note">${icon('leaf')}AI는 저장된 가족 기록을 참고해요. 아직 정리되지 않은 소식은 검색되지 않을 수 있어요.</p>`;
}
async function renderDigest(version) {
  $('#page').innerHTML = `${pageHeading('A DAY TO REMEMBER', '하루 모아보기', '바쁜 하루 사이 놓친 가족의 소식, 한 편의 이야기로 만나보세요.')}<div class="digest-layout"><aside class="panel date-panel"><h2>${icon('calendar')}날짜 선택</h2><label class="field"><span>한국 시간 기준</span><input id="digest-date" type="date" value="${today()}" max="${today()}" required></label><div id="digest-dates">${loading()}</div></aside><section class="panel digest-content" id="digest-result" aria-live="polite">${loading('오늘의 이야기를 모으고 있어요')}</section></div>`;
  const history = api('digests/history/').then(result => {
    if (version !== state.pageVersion) return;
    $('#digest-dates').innerHTML = `<p class="eyebrow">소식이 있는 날</p>${result.dates.map(date => `<button type="button" class="date-item ${date === today() ? 'selected' : ''}" data-action="digest-date" data-date="${date}" aria-pressed="${date === today()}">${icon('book')}${e(date)}${icon('chevron')}</button>`).join('')}`;
  }).catch(error => { if (version === state.pageVersion) $('#digest-dates').innerHTML = errorBlock(error.message); });
  await Promise.all([history, loadDigest(today(), false, version)]);
}
async function loadDigest(date, retry = false, version = state.pageVersion) {
  if (!date) return;
  const requestId = Symbol();
  state.digestRequest = requestId;
  $('#digest-result').innerHTML = loading('하루의 이야기를 모으고 있어요');
  stopAudio();
  state.digest = null;
  try {
    const result = await api(retry ? 'digests/' : `digests/?date=${encodeURIComponent(date)}`, retry ? { method: 'POST', data: { date } } : {});
    if (version !== state.pageVersion || state.digestRequest !== requestId) return;
    state.digest = result;
    const content = $('#digest-result');
    const header = `<p class="eyebrow">${e(result.date)} · ${e(result.digest_time)} 기준</p><h2>가족의 하루를 담았어요</h2>`;
    if (result.status === 'ready') content.innerHTML = `${header}<div class="digest-reading"><span class="tag">${icon('sparkle')}AI가 모은 가족 소식</span><p class="digest-text">${e(result.text)}</p><div class="button-row">${button('digest-audio', '이야기 듣기', 'volume', 'button secondary')}${button('stop-audio', '듣기 중지', 'stop', 'button quiet', 'hidden')}</div></div><h3 class="digest-post-heading">이날의 소식 ${result.posts.length}개</h3><div class="digest-posts">${result.posts.map(post => `<button type="button" class="digest-post" data-action="open-post" data-id="${post.id}">${avatar(post.author_name, post.author_id)}<span><strong>${e(post.author_name)}</strong><span>${e(post.caption || '사진으로 전한 소식')}</span></span>${icon('chevron')}</button>`).join('')}</div>`;
    else if (result.status === 'empty') content.innerHTML = header + empty('leaf', '조용히 지나간 하루예요', '이 시간대에는 가족이 남긴 소식이 없어요. 다른 날짜도 살펴보세요.');
    else if (result.status === 'failed') content.innerHTML = header + empty('book', '이야기를 모으지 못했어요', '잠시 후 다시 시도해 주세요.', button('retry-digest', '요약 다시 만들기', 'refresh'));
    else content.innerHTML = header + empty('book', result.status === 'pending' ? '이야기가 모일 시간을 기다려요' : '가족의 하루를 정리하고 있어요', result.status === 'pending' ? `한국 시간 ${e(result.digest_time)} 이후에 하루 요약을 만날 수 있어요.` : '잠시 후 새로고침해 주세요.', button('retry-digest', '다시 확인하기', 'refresh'));
  } catch (error) { if (version === state.pageVersion && state.digestRequest === requestId) $('#digest-result').innerHTML = errorBlock(error.message) + button('retry-digest', '다시 불러오기', 'refresh'); }
}
function renderFamily() {
  const owner = state.room.members.some(member => member.id === state.user.user_id && member.is_owner);
  $('#page').innerHTML = `${pageHeading('CLOSER, TOGETHER', '우리 가족', '가족의 연결을 가계도에서 살펴보세요.', button('refresh-page', '가계도 새로고침', 'refresh'))}<div class="family-layout"><section class="panel"><div class="section-heading"><div><p class="eyebrow">FAMILY ROOM</p><h2>${e(state.room.name)}</h2></div><span class="tag">${state.room.members.length}명의 가족</span></div>${treeMarkup(new FamilyTreeDraft(state.room.tree), { userId: state.user.user_id, members: state.room.members })}<p class="help">가입한 가족 ${state.room.members.length}명 · 가계도 속 사람 ${state.room.tree.people.length}명</p></section><aside><section class="panel invitation-card"><span class="empty-icon">${icon('heart')}</span><h2>가족을 초대해 보세요</h2><p class="muted">초대코드와 가족방 비밀번호를<br>가족에게 함께 알려주세요.</p><div class="invite-code">${e(state.room.invite_code)}</div>${button('copy-code', '초대코드 복사', 'copy', 'button secondary full')}<p class="help">참여할 때, 가계도에서 내 자리를 선택해 주세요.</p></section><section class="panel digest-settings"><h2>${icon('calendar')}하루 요약 시간</h2>${owner ? `<form data-form="digest-time">${field('매일, 한국 시간 기준', 'digest_time', 'time', `value="${e(state.room.digest_time)}" required`)}<p class="form-error" role="alert"></p><button type="submit" class="button secondary full">시간 저장하기</button></form>` : `<strong class="time-display">${e(state.room.digest_time)}</strong><p class="help">가족방을 만든 사람이 변경할 수 있어요.</p>`}</section></aside></div>`;
  mountTree($('#page .family-tree-board'), new FamilyTreeDraft(state.room.tree));
}
function renderSettings() {
  $('#page').innerHTML = `${pageHeading('YOUR LITTLE SPACE', '계정 설정', '가족에게 보여줄 내 정보를 관리해요.')}<div class="settings-grid"><section class="panel"><h2>내 프로필</h2><div class="settings-profile">${avatar(state.user.name, state.user.user_id, 'large')}<div><strong>${e(state.user.name)}</strong><p class="muted">@${e(state.user.username)}</p></div></div><form data-form="profile">${field('가족에게 보여줄 이름', 'name', 'text', `value="${e(state.user.name)}" maxlength="40" required autocomplete="name"`)}<p class="form-error" role="alert"></p><button class="button primary" type="submit">이름 저장하기</button></form></section><section class="panel"><h2>비밀번호 변경</h2><p class="muted">변경하면 다른 기기의 로그인은 해제돼요.</p><form data-form="password">${field('현재 비밀번호', 'current_password', 'password', 'required maxlength="128" autocomplete="current-password"')}${field('새 비밀번호', 'new_password', 'password', 'required minlength="10" maxlength="128" autocomplete="new-password"')}${field('새 비밀번호 확인', 'confirm_password', 'password', 'required minlength="10" maxlength="128" autocomplete="new-password"')}<p class="help">숫자를 포함한 10자 이상. 아이디·이름과 비슷하거나 흔한 값은 피해주세요.</p><p class="form-error" role="alert"></p><button class="button secondary" type="submit">비밀번호 변경하기</button></form></section></div>`;
}

function stopRecording(discard = false) {
  clearTimeout(recordingTimer);
  if (recorder && recorder.state !== 'inactive') {
    if (discard) recorder.onstop = null;
    recorder.stop();
  }
  recordingStream?.getTracks().forEach(track => track.stop());
  recordingStream = null;
  recorder = null;
}
async function startRecording() {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new ApiError('음성 답장은 localhost 또는 HTTPS에서 지원되는 브라우저로 이용해 주세요.');
  if (recorder) return;
  const version = state.modalVersion;
  const postId = state.detail.id;
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { throw new ApiError('마이크를 사용할 수 없어요. 브라우저의 마이크 권한과 연결을 확인해 주세요.'); }
  if (version !== state.modalVersion) { stream.getTracks().forEach(track => track.stop()); return; }
  const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
  if (!mimeType) { stream.getTracks().forEach(track => track.stop()); throw new ApiError('이 브라우저의 녹음 형식을 지원하지 않아요. 최신 Chrome 또는 Edge로 이용해 주세요.'); }
  let current;
  try { current = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64000 }); }
  catch { stream.getTracks().forEach(track => track.stop()); throw new ApiError('녹음을 시작하지 못했어요. 마이크 설정을 확인해 주세요.'); }
  recorder = current;
  recordingStream = stream;
  const chunks = [];
  let bytes = 0;
  current.ondataavailable = event => { chunks.push(event.data); bytes += event.data.size; if (bytes > 4.5 * 1024 * 1024) stopRecording(); };
  current.onerror = () => { stopRecording(true); if (version === state.modalVersion) $('#voice-panel').innerHTML = errorBlock('녹음 중 문제가 생겼어요. 다시 시도해 주세요.'); };
  current.onstop = async () => {
    stream.getTracks().forEach(track => track.stop());
    if (version !== state.modalVersion) return;
    const blob = new Blob(chunks, { type: mimeType });
    if (!blob.size || blob.size > 5 * 1024 * 1024) { $('#voice-panel').innerHTML = errorBlock('녹음이 비어 있거나 너무 커요. 짧게 다시 녹음해 주세요.'); return; }
    $('#voice-panel').innerHTML = loading('말씀을 글로 옮기고 있어요');
    try {
      const data = new FormData();
      const extension = mimeType.includes('mp4') ? 'm4a' : mimeType.includes('ogg') ? 'ogg' : 'webm';
      data.append('audio', blob, `reply.${extension}`);
      const result = await api(`posts/${postId}/replies/transcribe/`, { method: 'POST', data });
      if (version !== state.modalVersion) return;
      $('#voice-panel').innerHTML = `<div class="voice-review"><h4>${icon('mic')}말씀하신 내용을 확인해 주세요</h4><form data-form="voice-prepare"><label class="field"><span>잘못 인식된 부분은 고칠 수 있어요.</span><textarea name="recognized" required maxlength="2000" rows="3">${e(result.recognized)}</textarea></label><p class="form-error" role="alert"></p><button type="submit" class="button secondary">다정한 답장으로 정리하기${icon('sparkle')}</button></form></div>`;
    } catch (error) { if (version === state.modalVersion) $('#voice-panel').innerHTML = errorBlock(error.message) + button('record', '다시 녹음하기', 'mic'); }
  };
  current.start(1000);
  recordingTimer = setTimeout(() => { stopRecording(); toast('2분이 되어 녹음을 마쳤어요.'); }, 120000);
  $('#voice-panel').innerHTML = `<div class="recording-status"><span class="recording-dot"></span><span>녹음 중이에요 · 최대 2분</span>${button('finish-record', '녹음 마치기', 'stop', 'button primary compact')}${button('cancel-record', '취소', '', 'button quiet compact')}</div>`;
}

const formHandlers = {
  async login(data) {
    const result = await api('accounts/login/', { method: 'POST', data });
    setToken(result.token);
    await enterApp();
  },
  async register(data) {
    const result = await api('accounts/register/', { method: 'POST', data });
    setToken(result.token);
    await enterApp();
  },
  async 'create-room'(data) {
    const result = await api('families/create/', { method: 'POST', data });
    state.room = result.room;
    location.hash = '#/feed';
    renderShell();
    await renderPage();
  },
  async 'lookup-room'(data) {
    state.lookup = null;
    $('#join-panel').innerHTML = '';
    const session = state.session;
    const room = await api('families/lookup/', { method: 'POST', data });
    if (session !== state.session || !$('#join-panel')) return;
    const form = $('[data-form="lookup-room"]');
    if ($('[name="invite_code"]', form).value !== data.invite_code || $('[name="password"]', form).value !== data.password) return;
    state.lookup = { ...data, room, draft: new FamilyTreeDraft(room.tree) };
    renderJoinPreview();
  },
  async 'join-room'(data) {
    if (!state.lookup) throw new ApiError('가족방을 먼저 확인해 주세요.');
    const lookup = state.lookup;
    const session = state.session;
    lookup.draft.selectedId = data.person_id;
    let result;
    try {
      result = await api('families/join/', { method: 'POST', data: {
        invite_code: lookup.invite_code, password: lookup.password, ...lookup.draft.payload(state.user.gender),
      } });
    } catch (error) {
      if (error.status === 409 && state.lookup === lookup) {
        const room = await api('families/lookup/', { method: 'POST', data: { invite_code: lookup.invite_code, password: lookup.password } });
        if (state.lookup === lookup) {
          state.lookup = { ...lookup, room, draft: new FamilyTreeDraft(room.tree) };
          renderJoinPreview('가계도가 바뀌었어요. 추가한 내용을 초기화했으니 최신 가계도에서 내 자리를 다시 선택해 주세요.');
        }
        return;
      }
      throw error;
    }
    if (session !== state.session) return;
    state.lookup = null;
    state.room = result.room;
    location.hash = '#/feed';
    renderShell();
    await renderPage();
  },
  async post(data) {
    if (!data.caption.trim() && !state.files.length) throw new ApiError('글이나 사진을 하나 이상 남겨 주세요.');
    const version = state.modalVersion;
    const body = new FormData();
    body.append('caption', data.caption);
    state.files.forEach(file => body.append('images', file, file.name));
    await api('posts/', { method: 'POST', data: body });
    if (version === state.modalVersion) modal.close();
    toast('가족에게 소식을 전했어요.');
    if (currentRoute() === 'feed') await renderPage();
    else location.hash = '#/feed';
  },
  async comment(data, form) {
    const version = state.modalVersion;
    const postId = state.detail.id;
    await api(`posts/${postId}/comments/`, { method: 'POST', data });
    if (version !== state.modalVersion) return;
    form.reset();
    const result = await api(`posts/${postId}/`);
    if (version !== state.modalVersion) return;
    state.detail.comments = result.comments;
    renderComments();
    const post = state.posts.find(item => item.id === postId);
    if (post) { post.comment_count = result.comments.length; if ($('#feed-list')) updateFeed(); }
    toast('따뜻한 마음을 전했어요.');
  },
  async 'post-question'(data, form) {
    const version = state.modalVersion;
    const result = await api(`posts/${state.detail.id}/questions/`, { method: 'POST', data: { question: data.question, prior_dialogue: state.dialogue.slice(-10).map(turn => ({ ...turn, text: turn.text.slice(0, 1000) })) } });
    if (version !== state.modalVersion) return;
    state.dialogue.push({ role: 'user', text: data.question }, { role: 'assistant', text: result.text });
    $('#question-history').innerHTML = state.dialogue.map(turn => `<div class="chat-turn ${turn.role}"><span>${turn.role === 'user' ? '나의 질문' : '토닥 AI'}</span><p>${e(turn.text)}</p></div>`).join('');
    form.reset();
  },
  async search(data) {
    const version = state.pageVersion;
    $('#search-result').innerHTML = loading('가족의 추억을 찾고 있어요');
    try {
      const result = await api('searching/history/', { method: 'POST', data });
      if (version !== state.pageVersion) return;
      $('#search-result').innerHTML = `<section class="panel search-answer"><p class="eyebrow">${icon('sparkle')}토닥이 찾은 이야기</p><h2>${e(data.question)}</h2><p class="answer-text">${e(result.text)}</p><p class="help">가족 기록을 참고한 AI 답변이에요. 중요한 내용은 가족에게 확인해 주세요.</p></section>`;
    } catch (error) { if (version === state.pageVersion) $('#search-result').innerHTML = ''; throw error; }
  },
  async 'digest-time'(data) {
    state.room = await api('families/current/', { method: 'PATCH', data });
    toast('하루 요약 시간을 저장했어요.');
  },
  async profile(data) {
    const result = await api('accounts/me/', { method: 'PATCH', data });
    state.user = { ...state.user, ...result };
    state.room = await api('families/current/');
    renderShell();
    await renderPage();
    toast('이름을 저장했어요.');
  },
  async password(data, form) {
    if (data.new_password !== data.confirm_password) throw new ApiError('새 비밀번호와 확인 값이 달라요.');
    const result = await api('accounts/me/', { method: 'PATCH', data: { current_password: data.current_password, new_password: data.new_password } });
    setToken(result.token);
    form.reset();
    toast('비밀번호를 변경했어요.');
  },
  async 'voice-prepare'(data) {
    const version = state.modalVersion;
    const draft = await api(`posts/${state.detail.id}/replies/prepare/`, { method: 'POST', data });
    if (version !== state.modalVersion) return;
    $('#voice-panel').innerHTML = `<div class="voice-review"><span class="tag">보내기 전 마지막 확인</span><h4>이렇게 마음을 전할까요?</h4><p class="voice-draft">${e(draft.converted)}</p><p class="help">아래 버튼을 누르면 이 글이 가족 댓글로 전송돼요.</p><div class="button-row">${button('send-voice', '이대로 답장 보내기', 'arrow', 'button primary', `data-id="${draft.id}"`)}${button('cancel-record', '취소', '', 'button quiet')}</div></div>`;
  },
};

document.addEventListener('submit', async event => {
  const form = event.target.closest('form[data-form]');
  if (!form) return;
  event.preventDefault();
  if (form.dataset.pending) return;
  const handler = formHandlers[form.dataset.form];
  if (!handler) return;
  form.dataset.pending = 'true';
  const data = Object.fromEntries(new FormData(form));
  try { await busy(event.submitter || $('[type="submit"]', form), () => handler(data, form), $('.form-error', form)); }
  finally { delete form.dataset.pending; }
});

document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]');
  if (!target || target.disabled) return;
  const action = target.dataset.action;
  if (action === 'auth-login') return renderAuth(false);
  if (action === 'auth-register') return renderAuth(true);
  if (action === 'close-modal') return modal.close();
  if (action === 'text-size') {
    const large = document.documentElement.classList.toggle('large-text');
    localStorage.setItem('talkdock.web.largeText', String(large));
    target.setAttribute('aria-pressed', String(large));
    return;
  }
  if (action === 'undo-tree' && state.lookup) { state.lookup.draft.undo(); renderJoinPreview(); return; }
  if (action === 'compose') return openComposer();
  if (action === 'open-post' || action === 'retry-post' || action === 'post-summary') return openPost(Number(target.dataset.id), action === 'post-summary');
  if (action === 'select-photo') return showPhoto(Number(target.dataset.index));
  if (action === 'remove-photo') { state.files.splice(Number(target.dataset.index), 1); return renderPreviews(); }
  if (action === 'refresh-page' || action === 'refresh-feed') return renderPage();
  if (action === 'stop-audio') return stopAudio();
  if (action === 'cancel-record') { stopRecording(true); $('#voice-panel').innerHTML = ''; return; }
  if (action === 'finish-record') { stopRecording(); return; }
  if (action === 'search-suggestion') { $('#memory-question').value = target.dataset.question; $('#memory-question').focus(); return; }
  if (action === 'digest-date') {
    $('#digest-date').value = target.dataset.date;
    document.querySelectorAll('.date-item').forEach(node => { const selected = node === target; node.classList.toggle('selected', selected); node.setAttribute('aria-pressed', String(selected)); });
    return loadDigest(target.dataset.date);
  }
  await busy(target, async () => {
    if (action === 'reload-tree' && state.lookup) {
      const lookup = state.lookup;
      const room = await api('families/lookup/', { method: 'POST', data: { invite_code: lookup.invite_code, password: lookup.password } });
      if (state.lookup === lookup) {
        state.lookup = { ...lookup, room, draft: new FamilyTreeDraft(room.tree) };
        renderJoinPreview();
      }
    }
    if (action === 'logout') {
      // Keep the session if revocation fails so the user can retry explicitly.
      await api('accounts/logout/', { method: 'POST' });
      resetSession(); renderAuth();
    }
    if (action === 'copy-code') {
      if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(state.room.invite_code); toast('초대코드를 복사했어요.'); }
      else toast(`초대코드: ${state.room.invite_code} · 코드를 직접 복사해 주세요.`);
    }
    if (action === 'summary') await loadSummary();
    if (action === 'summary-audio') {
      const version = state.modalVersion;
      if (!state.detail.summary) await loadSummary();
      if (version === state.modalVersion && state.detail?.summary) await playSpeech(state.detail.summary, $('[data-action="stop-audio"]', modal), () => version === state.modalVersion);
    }
    if (action === 'digest-audio') {
      const version = state.pageVersion;
      const digest = state.digest;
      await playSpeech(digest.text, $('[data-action="stop-audio"]', $('#digest-result')), () => version === state.pageVersion && digest === state.digest);
    }
    if (action === 'retry-digest') await loadDigest($('#digest-date').value, true);
    if (action === 'record') await startRecording();
    if (action === 'send-voice') {
      const version = state.modalVersion;
      const postId = state.detail.id;
      await api(`replies/${Number(target.dataset.id)}/send/`, { method: 'POST' });
      if (version !== state.modalVersion) return;
      // Remove the send button immediately: draft publication is idempotent.
      $('#voice-panel').innerHTML = '<p class="success">마음을 전했어요.</p>';
      const post = await api(`posts/${postId}/`);
      if (version !== state.modalVersion) return;
      state.detail.comments = post.comments;
      renderComments();
      const feedPost = state.posts.find(item => item.id === postId);
      if (feedPost) { feedPost.comment_count = post.comments.length; if ($('#feed-list')) updateFeed(); }
      toast('음성 답장을 전했어요.');
    }
  });
});
document.addEventListener('input', event => {
  if (event.target.id === 'feed-filter') updateFeed();
  if (event.target.id === 'post-caption') $('#caption-count').textContent = event.target.value.length;
  if (event.target.closest('[data-form="lookup-room"]')) { state.lookup = null; $('#join-panel').innerHTML = ''; }
});
document.addEventListener('change', event => {
  if (event.target.id === 'author-filter') updateFeed();
  if (event.target.id === 'photo-input') { addFiles([...event.target.files]); event.target.value = ''; }
  if (event.target.id === 'digest-date' && event.target.validity.valid) {
    document.querySelectorAll('.date-item').forEach(node => { const selected = node.dataset.date === event.target.value; node.classList.toggle('selected', selected); node.setAttribute('aria-pressed', String(selected)); });
    loadDigest(event.target.value);
  }
});
document.addEventListener('dragover', event => { const zone = event.target.closest('#drop-zone'); if (zone) { event.preventDefault(); zone.classList.add('dragging'); } });
document.addEventListener('dragleave', event => { event.target.closest('#drop-zone')?.classList.remove('dragging'); });
document.addEventListener('drop', event => { const zone = event.target.closest('#drop-zone'); if (zone) { event.preventDefault(); zone.classList.remove('dragging'); addFiles([...event.dataTransfer.files]); } });
document.addEventListener('keydown', event => {
  if (event.target.id === 'drop-zone' && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); $('#photo-input').click(); }
  if (modal.open && state.detail && !['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(event.target.tagName)) {
    if (event.key === 'ArrowRight') showPhoto((state.photoIndex + 1) % Math.max(1, state.detail.images.length));
    if (event.key === 'ArrowLeft') showPhoto((state.photoIndex - 1 + state.detail.images.length) % Math.max(1, state.detail.images.length));
  }
});
window.addEventListener('pagehide', () => { stopRecording(true); stopAudio(); clearImages(); });
document.documentElement.classList.toggle('large-text', localStorage.getItem('talkdock.web.largeText') === 'true');
if (hasToken()) {
  enterApp().catch(error => { if (hasToken()) { app.innerHTML = `<main id="main" class="boot">${errorBlock(error.message)}${button('retry-enter', '다시 연결하기', 'refresh')}${button('logout', '로그아웃', 'logout', 'button quiet')}</main>`; } });
} else renderAuth();
document.addEventListener('click', event => { const target = event.target.closest('[data-action="retry-enter"]'); if (target) busy(target, enterApp); });
