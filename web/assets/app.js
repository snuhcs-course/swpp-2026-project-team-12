import { VoicePreview } from './voice-preview.js';
import { readMode, writeMode, calendarDays, koreanDay, captionNeedsMore, replyPrompt, withReplyPrompt } from './ui-modes.js';
import { GuidedHelp } from './guided-help.js';
import { api, ApiError, registrationPayload, hasToken, setToken, setRoom, imageURL, clearImages } from './api.js';
import { icon } from './icons.js';
import { FamilyTreeDraft } from './family-tree.js';
import { treeMarkup, mountTree } from './family-tree-view.js';
import { FloatingAssistant } from './floating-assistant.js?v=ui-modes-20261109';
import { memoryEvidence } from './memory-search.js';
import { questionEntry, questionMarkup, questionHistory, questionPayload, questionVersion } from './daily-questions.js';
import { postDraft, savePostDraft, clearPostDraft, commentDraft, saveCommentDraft, clearCommentIfSent, pastQuestions, rememberQuestion, pastQuestionsMarkup, clearAccountDrafts, memorySearches, rememberMemorySearch, pastMemoriesMarkup } from './local-drafts.js';

const app = document.querySelector('#app');
const modal = document.querySelector('#modal');
const toastBox = document.querySelector('#toast');
const busyIndicator = document.querySelector('#busy-indicator');
const postingSuccessBox = document.querySelector('#posting-success');
let postingSuccessTimer;
let elder = false, inlineObserver, captionObserver, selectedDigestDate = null, digestMonth = null, digestDates = [];
const preferredModes = new Map();
const expandedPosts = new Set(), inlineComments = new Map(), pendingComments = new Set();
let commentQueue = [], commentActive = 0;
const help = new GuidedHelp();
function applyScreenMode() {
  elder = state.user && (preferredModes.get(state.user.user_id) || readMode(localStorage, state.user.user_id)) === 'elder';
  document.documentElement.classList.toggle('elder-screen', Boolean(elder));
  document.documentElement.classList.toggle('large-text', Boolean(elder));
}
const seenGuides = new Set();
let replyCheckTimer;
function guideSeen(key) {
  try { return seenGuides.has(key) || localStorage.getItem(key) === 'true'; }
  catch { return seenGuides.has(key); }
}
function markGuideSeen(key) {
  seenGuides.add(key);
  try { localStorage.setItem(key, 'true'); } catch {}
}
function guideKeys() {
  const basic = `talkdock.web.help:v2:${state.user.user_id}`;
  return { basic, reply: `${basic}:reply:${state.room.id}` };
}
function otherPost(posts) {
  return posts.find(post => Number(post.author_id) > 0 && Number(post.author_id) !== Number(state.user.user_id));
}
function openPractice(manual = false) {
  const keys = guideKeys();
  const post = otherPost(state.posts);
  const replyPost = manual || !guideSeen(keys.reply) ? post : null;
  const replyOnly = !manual && guideSeen(keys.basic);
  if (help.dialog?.open || (replyOnly && !replyPost)) return;
  if (!replyOnly) markGuideSeen(keys.basic);
  help.open({ post: replyPost, replyOnly, elder, onReplyShown: () => markGuideSeen(keys.reply) });
}
function maybeShowHelp() {
  if (elder && !document.querySelector('dialog[open]') && currentRoute() === 'feed') openPractice();
}
function stopReplyCheck() {
  clearTimeout(replyCheckTimer);
}
function scheduleReplyCheck() {
  stopReplyCheck();
  if (!elder || !state.user || !state.room || currentRoute() !== 'feed' || guideSeen(guideKeys().reply)) return;
  const version = state.pageVersion, room = state.room.id, session = state.session;
  const current = () => version === state.pageVersion && session === state.session &&
    state.room?.id === room && currentRoute() === 'feed' && elder;
  const idle = () => !document.hidden && !document.querySelector('dialog[open]') && !pendingOperations.size &&
    !document.querySelector('#feed-list .elder-reply');
  replyCheckTimer = setTimeout(async () => {
    if (!current() || guideSeen(guideKeys().reply)) return;
    if (idle()) {
      if (!otherPost(state.posts)) {
        try {
          const result = await api('posts/', { room });
          if (!current()) return;
          if (idle() && otherPost(result.posts)) {
            state.posts = result.posts;
            updateFeed();
          }
        } catch { /* A later check or feed refresh can pick up the post. */ }
      }
      if (current() && idle()) maybeShowHelp();
    }
    if (current()) scheduleReplyCheck();
  }, 20_000);
}
const pendingOperations = new Set();
function memoryResultMarkup(text, evidence) {
  return `<div class="feed-layout memory-results"><div><section class="panel search-answer"><p class="answer-text">${e(text)}</p>${elder ? `${button('memory-audio', '답변 듣기', 'volume', 'button primary full')}${button('stop-audio', '듣기 중지', 'stop', 'button quiet', 'hidden')}` : ''}</section><section class="memory-evidence" aria-label="답변에 참고한 가족 소식">${evidence.posts.map(memoryPostCard).join('')}${evidence.unavailable ? '<p class="help" role="status">일부 소식을 불러오지 못했어요. 잠시 후 다시 찾아주세요.</p>' : !evidence.posts.length ? '<p class="help">함께 보여드릴 소식을 찾지 못했어요.</p>' : ''}</section></div></div>`;
}
const draftScope = () => state.user && state.room ? `${state.user.user_id}:${state.room.id}` : null;
document.addEventListener('input', event => {
  const field = event.target, scope = draftScope();
  if (!scope || !(field instanceof HTMLTextAreaElement)) return;
  if (field.id === 'post-caption') savePostDraft(scope, field.value);
  else if (field.id === 'comment-text' && state.detail) saveCommentDraft(scope, state.detail.id, field.value);
  else if (field.closest('[data-form="elder-reply"]')) saveCommentDraft(scope, Number(field.closest('form').dataset.id), field.value);
});
function restoreDraft(field, text) {
  if (!field || !text || field.value) return false;
  field.value = text; field.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
}
function questionHistoryMarkup() {
  const past = state.detail ? pastQuestions(draftScope(), state.detail.id) : [];
  return pastQuestionsMarkup(past, e, { user: '나의 질문', assistant: '토닥 AI' }) + state.dialogue.map(turn => `<div class="chat-turn ${turn.role}"><span>${turn.role === 'user' ? '나의 질문' : '토닥 AI'}</span><p>${e(turn.text)}</p></div>`).join('');
}
const state = { user: null, room: null, rooms: [], posts: [], detail: null, dialogue: [], files: [], lookup: null, pageVersion: 0, modalVersion: 0, session: 0, digest: null, photoIndex: 0 };
const assistant = new FloatingAssistant({
  root: document.querySelector('#assistant-root'),
  context: () => ({
    scope: state.user && state.room ? `${state.user.user_id}:${state.room.id}` : null,
    roomId: state.room?.id,
    // The elderly screen reaches every feature from the card or the bottom tabs instead.
    enabled: Boolean(!elder && state.user && state.room && currentRoute() === 'feed' && document.querySelector('#feed-list') && !modal.open),
  }),
  ask: ({ id, roomId, question, dialogue }) => api(`posts/${id}/questions/`, {
    method: 'POST', room: roomId, data: { question, prior_dialogue: dialogue },
  }),
});
const nav = [['feed', 'home', '소식'], ['digest', 'calendar', '하루'], ['search', 'search', '추억']];
let toastTimer, observer, audio, audioURL, recorder, recordingStream, recordingTimer;
let recordingRequest = 0;
let elderRecording = false;
let audioGeneration = 0;
// Elderly tab tour: the next step waits until the playback it started has ended, been stopped or failed.
let afterAudio = null;
function whenAudioEnds(fn) { afterAudio = { generation: 0, fn }; }
function updatePostViewport() {
  const viewport = window.visualViewport;
  document.documentElement.style.setProperty('--post-viewport-height', `${viewport?.height || innerHeight}px`);
  document.documentElement.style.setProperty('--post-viewport-top', `${viewport?.offsetTop || 0}px`);
  document.documentElement.style.setProperty('--post-viewport-bottom', `${Math.max(0, innerHeight - (viewport?.height || innerHeight) - (viewport?.offsetTop || 0))}px`);
}
window.visualViewport?.addEventListener('resize', updatePostViewport);
window.visualViewport?.addEventListener('scroll', updatePostViewport);
window.addEventListener('resize', updatePostViewport);
updatePostViewport();
let previewURLs = [];
let voicePreview = null;
let maintenanceNotice, reconnecting = false;
let dailyStatus = null, dailyQuestion = null, dailyDraft = null, dailyRequest = 0, dailyHistoryRows = [];
const dailyDrafts = new Map();

window.addEventListener('server-maintenance', () => {
  if (!maintenanceNotice) {
    maintenanceNotice = document.createElement('dialog');
    maintenanceNotice.className = 'maintenance-notice';
    maintenanceNotice.setAttribute('aria-label', '잠시 이용이 어려워요');
    maintenanceNotice.innerHTML = '<iframe src="/maintenance/" title="서비스 점검 안내"></iframe>';
    maintenanceNotice.addEventListener('cancel', event => event.preventDefault());
    document.body.append(maintenanceNotice);
  }
  stopAudio();
  if (!maintenanceNotice.open) maintenanceNotice.showModal();
});
window.addEventListener('message', async event => {
  if (!maintenanceNotice?.open || reconnecting || event.origin !== window.location.origin ||
      event.source !== maintenanceNotice.querySelector('iframe').contentWindow ||
      event.data !== 'talkdock-maintenance-retry') return;
  reconnecting = true;
  try {
    await api('test_reply/', { room: null });
    maintenanceNotice.close();
    if (document.querySelector('#main.boot')) {
      if (hasToken()) await connectSession(); else renderAuth();
    }
  } catch { /* Keep the notice visible until the server is reachable. */ }
  finally { reconnecting = false; }
});

const e = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const $ = (selector, root = document) => root.querySelector(selector);
const avatar = (name, id = 0, size = '') => `<span class="avatar tone-${Math.abs(Number(id) || 0) % 5} ${size}" aria-hidden="true">${e([...String(name || '가')][0])}</span>`;
const brand = () => '<a class="brand" href="#/feed" aria-label="토닥 홈"><img src="/web/assets/favicon.svg?v=family-20261102" alt="" width="42" height="42"><span>토닥<small>TALK DOCK</small></span></a>';
const button = (action, label, symbol, cls = 'button secondary', extra = '') => `<button type="button" class="${cls}" data-action="${action}" ${extra}>${symbol ? icon(symbol) : ''}${label}</button>`;
const character = (sad = false, classes = '') => `<span class="character-art ${sad ? 'character-sad' : 'character-boy'} ${classes}" aria-hidden="true"></span>`;
const loading = (text = '불러오는 중이에요') => `<div class="loading" role="status">${character()}<span>${e(text)}</span></div>`;
const errorBlock = message => `<p class="error" role="alert">${e(message)}</p>`;
const failureContent = error => error.unavailable ? `${character(true)}<strong>잠시 후 다시 시도해 주세요</strong><span>${e(error.message)}</span>` : e(error.message || '다시 시도해 주세요.');
const failureBlock = (error, controls = '', title = '입력한 내용을 확인해 주세요') => error.unavailable ? `<section class="availability-notice panel" role="alert">${failureContent(error)}${controls}</section>` : `<section class="error" role="alert"><strong>${e(title)}</strong><p>${e(error.message)}</p>${controls}</section>`;
function hidePostingSuccess() {
  clearTimeout(postingSuccessTimer);
  postingSuccessBox.hidden = true;
  updateBusyIndicator();
}
function showPostingSuccess(message) {
  clearTimeout(postingSuccessTimer);
  (modal.open ? modal : document.body).append(postingSuccessBox);
  postingSuccessBox.innerHTML = `<span class="posting-success-card">${character(false, 'celebrating')}<strong>${e(message)}</strong></span>`;
  postingSuccessBox.hidden = false;
  updateBusyIndicator();
  postingSuccessTimer = setTimeout(hidePostingSuccess, 3000);
}
function renderEntryFailure(error) {
  app.innerHTML = `<main id="main" class="boot">${failureBlock(error, button('retry-enter', '다시 연결하기', 'refresh'))}${button('logout', '로그아웃', 'logout', 'button quiet')}</main>`;
}
async function connectSession() {
  app.innerHTML = `<main id="main" class="boot">${loading('가족방에 연결하고 있어요')}</main>`;
  try { await enterApp(); }
  catch (error) { if (hasToken()) renderEntryFailure(error); }
}
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
  toastBox.classList.remove('availability-toast');
  toastBox.textContent = message;
  toastBox.hidden = false;
  toastTimer = setTimeout(() => { toastBox.hidden = true; }, 5000);
}
function notifyFailure(error) {
  if (!error.unavailable) return toast(error.message || '다시 시도해 주세요.');
  toast('');
  toastBox.classList.add('availability-toast');
  toastBox.innerHTML = failureContent(error);
}
function field(label, name, type = 'text', attrs = '') {
  return `<label class="field"><span>${label}</span><input name="${name}" type="${type}" ${attrs}></label>`;
}
function showFieldError(form, error) {
  const input = form?.elements.namedItem(error.field);
  if (!input) return false;
  let message = input.parentElement.querySelector('.field-error');
  if (!message) {
    message = document.createElement('span'); message.className = 'field-error';
    message.id = `error-${form.dataset.form}-${input.name}`; message.setAttribute('role', 'alert');
    input.after(message);
  }
  message.textContent = error.message;
  input.setAttribute('aria-invalid', 'true'); input.setAttribute('aria-describedby', message.id);
  input.focus(); input.scrollIntoView({ block: 'center', behavior: 'smooth' });
  return true;
}
function stopAudio() {
  const ending = afterAudio?.generation && afterAudio.generation === audioGeneration ? afterAudio.fn : null;
  if (ending) afterAudio = null;
  audioGeneration++;
  voicePreview?.cancel();
  if (audio) { audio.pause(); audio = null; }
  if (audioURL) { URL.revokeObjectURL(audioURL); audioURL = null; }
  document.querySelectorAll('.feed-audio-summary[data-preparing]').forEach(node => { node.hidden = true; });
  document.querySelectorAll('[data-action="stop-audio"]').forEach(node => { node.hidden = true; });
  document.querySelectorAll('[data-action="feed-stop-listen"]').forEach(node => { node.dataset.action = 'feed-listen'; node.innerHTML = icon('volume') + feedListenLabel(); node.setAttribute('aria-label','소식 듣기'); });
  ending?.();
}
function updateBusyIndicator() {
  const active = [...pendingOperations].some(operation =>
    operation.session === state.session && operation.pageVersion === state.pageVersion &&
    (operation.modalVersion === null || (modal.open && operation.modalVersion === state.modalVersion)));
  // Native dialogs occupy the browser's top layer. Keep the loading card inside
  // the open dialog so AI and voice requests remain visible above its backdrop.
  (modal.open ? modal : document.body).append(busyIndicator);
  busyIndicator.hidden = !active || !postingSuccessBox.hidden;
}
function cleanupModal() {
  captureDailyDraft(); dailyQuestion = null; dailyDraft = null; dailyRequest++;
  state.modalVersion++;
  state.detail = null;
  state.dialogue = [];
  stopRecording(true);
  stopAudio();
  previewURLs.forEach(url => URL.revokeObjectURL(url));
  previewURLs = [];
  state.files = [];
  document.body.append(toastBox, postingSuccessBox);
  updateBusyIndicator();
  document.body.classList.remove('modal-open');
  assistant.refresh();
}
function openModal(content, className = '') {
  assistant.close(false);
  if (modal.open) modal.close();
  cleanupModal();
  modal.className = className;
  modal.innerHTML = content;
  modal.showModal();
  document.body.classList.add('modal-open');
  assistant.refresh();
}
function modalHeading(title, eyebrow = '') {
  return `<header class="modal-heading"><div>${eyebrow ? `<p class="eyebrow">${eyebrow}</p>` : ''}<h2 id="modal-title">${title}</h2></div>${button('close-modal', '<span class="sr-only">닫기</span>', 'close', 'icon-button')}</header>`;
}
modal.addEventListener('close', () => { if (!modal.open) cleanupModal(); });
modal.addEventListener('click', event => { if (event.target === modal) { const rect = modal.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) modal.close(); } });

async function busy(element, task, errorTarget) {
  if (element?.disabled) return;
  hidePostingSuccess();
  let result;
  const original = element?.innerHTML;
  const session = state.session;
  const operation = { session, pageVersion: state.pageVersion, modalVersion: modal.contains(element) ? state.modalVersion : null };
  pendingOperations.add(operation);
  updateBusyIndicator();
  if (element) { element.disabled = true; element.setAttribute('aria-busy', 'true'); element.innerHTML = `${character(false, 'button-mascot')}<span class="sr-only">잠시만요</span>`; }
  if (errorTarget) { errorTarget.textContent = ''; errorTarget.classList.remove('availability-inline'); }
  try { result = await task(); }
  catch (error) {
    if (session !== state.session) return;
    if (error.field && showFieldError(errorTarget?.closest('form'), error)) return;
    if (errorTarget?.isConnected) { errorTarget.innerHTML = failureContent(error); errorTarget.classList.toggle('availability-inline', Boolean(error.unavailable)); }
    else notifyFailure(error);
  } finally {
    pendingOperations.delete(operation);
    updateBusyIndicator();
    if (element?.isConnected) { element.disabled = false; element.removeAttribute('aria-busy'); element.innerHTML = original; }
  }
  if (result?.postingMessage && session === state.session) showPostingSuccess(result.postingMessage);
}

function resetSession() {
  stopReplyCheck(); help.dialog?.close();
  inlineComments.clear(); pendingComments.clear(); commentQueue = []; expandedPosts.clear();
  assistant.reset();
  hidePostingSuccess();
  state.session++;
  state.pageVersion++;
  state.user = state.room = state.lookup = state.digest = null;
  state.posts = [];
  state.rooms = [];
  setToken('');
  setRoom(null);
  clearImages();
  stopAudio();
  if (modal.open) modal.close();
  dailyDrafts.clear(); dailyStatus = null;
  observer?.disconnect(); inlineObserver?.disconnect();
  updateBusyIndicator();
}
window.addEventListener('session-expired', () => { resetSession(); renderAuth(); toast('로그인 시간이 만료되었어요. 다시 로그인해 주세요.'); });

// The server owns the voice list, so adding a voice needs no web change.
let voiceList = null;
function loadVoices() {
  voiceList ??= api('speech/voices/').catch(error => { voiceList = null; throw error; });
  return voiceList;
}
// Without a real choice the field stays hidden and the server keeps its default.
async function fillVoiceSelect(select, selected) {
  let list;
  try { list = await loadVoices(); } catch { return; }
  if (!select?.isConnected || list.voices.length < 2) return;
  const current = list.voices.some(voice => voice.key === selected) ? selected : list.default;
  // Options show what each voice sounds like; a voice without a description shows its name.
  const title = voice => voice.description || voice.name;
  select.innerHTML = list.voices.map(voice => `<option value="${e(voice.key)}"${voice.key === current ? ' selected' : ''}>${e(title(voice))}</option>`).join('');
  const field = select.closest('[data-voice-field]');
  const note = field.querySelector('[data-voice-default]');
  const fallback = list.voices.find(voice => voice.key === list.default) ?? list.voices[0];
  if (note) note.textContent = `기본값: ${title(fallback)} · 계정 설정에서 언제든 바꿀 수 있어요.`;
  const sample = field.querySelector('[data-voice-sample]');
  sample.innerHTML = `${icon('volume')}미리 듣기`;
  const status = document.createElement('p');
  status.className = 'help voice-preview-status'; status.setAttribute('role', 'status'); sample.after(status);
  let player = null, url = null;
  const stop = () => { player?.pause(); player = null; if (url) URL.revokeObjectURL(url); url = null; };
  const preview = new VoicePreview({
    load: key => api(`speech/voices/${encodeURIComponent(key)}/sample/`, { binary: true }),
    current: key => select.isConnected && select.value === key && !document.hidden,
    status: text => { if (select.isConnected) status.textContent = text; },
    stop,
    play: async (blob, ended) => {
      url = URL.createObjectURL(blob); player = new Audio(url);
      const activePlayer = player;
      player.addEventListener('ended', () => { if (player === activePlayer) { stop(); ended(); } }, { once: true });
      player.addEventListener('error', () => {
        if (player === activePlayer) { stop(); status.textContent = '재생하지 못했어요. 미리 듣기를 다시 눌러 주세요.'; }
      }, { once: true });
      await player.play();
    },
  });
  voicePreview?.cancel(); voicePreview = preview;
  const showSample = () => {
    preview.cancel();
    sample.hidden = !list.voices.find(voice => voice.key === select.value)?.sample;
    if (!sample.hidden) preview.preload(select.value);
  };
  select.addEventListener('change', showSample);
  sample.addEventListener('click', () => { stopAudio(); preview.preview(select.value); });
  showSample(); field.hidden = false;
}
document.addEventListener('visibilitychange', () => { if (document.hidden) voicePreview?.cancel(); });

function renderAuth(register = false) {
  stopAudio();
  app.innerHTML = `<main id="main" class="auth-layout">
    <section class="auth-story">${brand()}<div class="story-copy"><p class="eyebrow">마음이 닿는 곳, 토닥</p><h1>작은 일상이 모여,<br>우리의 이야기가 돼요.</h1><p>멀리 있어도 가까이.<br>사진 한 장, 따뜻한 한마디로 안부를 나눠요.</p></div>
      <div class="story-art" aria-hidden="true"><div class="art-sun"></div><div class="art-window"><div class="art-hill"></div><div class="art-hill second"></div><span class="art-heart">${icon('heart')}</span></div><div class="art-note">${icon('leaf')}오늘도, 함께라서 좋은 날</div><div class="art-stamp">우리 가족의<br>소중한 순간들</div></div>
      <p class="story-foot">일상을 나누고, 마음을 잇습니다.</p></section>
    <section class="auth-panel"><div class="auth-form-wrap"><span class="tag">우리 가족만의 공간</span><h2>${register ? '반가워요, 처음 오셨나요?' : '다시 만나서 반가워요'}</h2><p class="muted">${register ? '계정을 만들고 가족의 이야기를 함께 시작해요.' : '가족의 새로운 이야기가 기다리고 있어요.'}</p>
      <div class="segmented" aria-label="계정 메뉴"><button type="button" data-action="auth-login" class="${register ? '' : 'selected'}" aria-pressed="${!register}">로그인</button><button type="button" data-action="auth-register" class="${register ? 'selected' : ''}" aria-pressed="${register}">회원가입</button></div>
      <form data-form="${register ? 'register' : 'login'}">
        ${register ? field('이름', 'name', 'text', 'required maxlength="40" autocomplete="name" placeholder="가족에게 보여줄 이름"') : ''}
        ${field('아이디', 'username', 'text', 'required maxlength="150" autocomplete="username" placeholder="아이디를 입력해 주세요" autocapitalize="none"')}
        ${field('비밀번호', 'password', 'password', `required maxlength="128"  autocomplete="${register ? 'new-password' : 'current-password'}" placeholder="${register ? '숫자를 포함한 10자 이상' : '비밀번호를 입력해 주세요'}"`)}
        ${register ? field('비밀번호 확인', 'confirm_password', 'password', 'required maxlength="128" autocomplete="new-password" placeholder="비밀번호를 한 번 더 입력해 주세요"') : ''}
        ${register ? '<label class="screen-choice"><input type="checkbox" name="screen_mode" value="elder">어르신 화면으로 시작하기</label>' : ''}
        ${register ? '<label class="field"><span>가족 관계 표시에 사용할 성별</span><select name="gender" required><option value="">성별을 선택해 주세요</option><option value="female">여성</option><option value="male">남성</option></select></label><div data-voice-field hidden><label class="field"><span>소식을 읽어 줄 목소리 (선택)</span><select name="tts_voice"></select></label><button type="button" class="button quiet compact" data-voice-sample hidden></button><p class="help" data-voice-default></p></div><p class="help">비밀번호는 숫자를 포함해 10자 이상으로 만들어 주세요. 아이디·이름과 비슷하거나 흔한 값, 숫자만으로는 만들 수 없어요.</p>' : ''}
        <p class="form-error" role="alert"></p><button class="button primary full" type="submit">${register ? '계정 만들기' : '우리 가족 만나러 가기'}${icon('arrow')}</button>
      </form><p class="auth-hint">${icon('heart')}안드로이드에서 쓰던 계정으로도 로그인할 수 있어요.</p></div></section></main>`;
  if (register) fillVoiceSelect($('form[data-form="register"] select[name="tts_voice"]'));
}

// The last opened room is remembered per account in this browser.
const roomKey = () => `talkdock.web.room.${state.user.user_id}`;
function savedRoom() {
  try { return Number(localStorage.getItem(roomKey())) || null; } catch { return null; }
}
function rememberRoom(id) {
  try { if (id) localStorage.setItem(roomKey(), String(id)); else localStorage.removeItem(roomKey()); } catch { /* Storage can be blocked. */ }
}

async function enterApp() {
  const session = state.session;
  state.user = await api('accounts/me/');
  if (session !== state.session) return;
  const { rooms } = await api('families/');
  if (session !== state.session) return;
  state.rooms = rooms;
  const chosen = rooms.find(room => room.id === savedRoom()) ?? (rooms.length === 1 ? rooms[0] : null);
  if (!chosen) return renderRoomChoice();
  await openRoom(chosen.id, { keepRoute: true });
}

function useRoom(room) {
  if (state.room?.id !== room.id) { assistant.reset(); dailyDrafts.clear(); dailyStatus = null; }
  state.room = room;
  state.posts = [];
  inlineComments.clear(); pendingComments.clear(); commentQueue = []; expandedPosts.clear();
  state.digest = state.lookup = null;
  setRoom(room.id);
  rememberRoom(room.id);
  clearImages();
}
// Switching rooms starts at the feed; reopening the app keeps the page in the address bar.
async function openRoom(id, { keepRoute = false } = {}) {
  const session = state.session;
  let room;
  // Pass the room explicitly so requests of the room on screen keep their header until the switch completes.
  try { room = await api('families/current/', { room: id }); }
  catch (error) {
    if (error.status !== 403 || session !== state.session) throw error;
    rememberRoom(null);
    state.room = null;
    setRoom(null);
    state.rooms = (await api('families/')).rooms;
    if (session === state.session) renderRoomChoice('그 가족방에는 더 이상 들어갈 수 없어요. 다른 가족방을 골라 주세요.');
    return;
  }
  if (session !== state.session) return;
  useRoom(room);
  if (!keepRoute) location.hash = '#/feed';
  renderShell();
  await renderPage();
}

function renderRoomChoice(message = '') {
  stopAudio();
  const joined = state.rooms.length > 0;
  app.innerHTML = `<main id="main" class="onboarding"><header>${brand()}${button('logout', '로그아웃', 'logout', 'button quiet')}</header>
    <div class="onboarding-intro"><p class="eyebrow">우리 가족, 여기서 만나요</p><h1>${e(state.user.name)}님, ${joined ? '어느 가족방으로 갈까요?' : '가족과 연결해 볼까요?'}</h1><p class="muted">${joined ? '들어갈 가족방을 고르거나, 새 가족방을 만들고 참여할 수 있어요.' : '새로운 가족방을 만들거나, 가족에게 받은 초대코드로 참여하세요.'}</p></div>
    ${message ? errorBlock(message) : ''}${roomList()}${roomForms()}</main>`;
}
function renderRooms() {
  $('#page').innerHTML = `${pageHeading('OUR FAMILY ROOMS', '가족방', '다른 가족방을 누르면 그 가족의 소식으로 바뀌어요.')}${roomList()}${roomForms()}`;
}
function roomList() {
  if (!state.rooms.length) return '';
  return `<ul class="room-list" aria-label="내 가족방">${state.rooms.map(room => {
    const current = room.id === state.room?.id;
    const details = [room.is_owner ? '내가 만든 방' : '', `${room.member_count}명`].filter(Boolean).join(' · ');
    return `<li><button type="button" class="room-card${current ? ' current' : ''}" data-action="open-room" data-id="${room.id}"${current ? ' aria-current="true"' : ''}><span class="empty-icon${current ? '' : ' sage'}">${icon('home')}</span><span class="room-card-text">${current ? '<span class="tag">지금 보는 가족방</span>' : ''}<strong>${e(room.name)}</strong><small>${details}</small></span>${icon('arrow')}</button></li>`;
  }).join('')}</ul>`;
}
function roomForms() {
  return `<div class="onboarding-grid"><section class="panel"><span class="empty-icon">${icon('home')}</span><h2>가족방 만들기</h2><p class="muted">우리 가족의 첫 이야기를 시작해요.</p><form data-form="create-room">${field('가족방 이름', 'room_name', 'text', 'required maxlength="60" placeholder="예: 행복이 피어나는 우리 집"')}${field('가족방 비밀번호', 'password', 'password', 'required maxlength="128" autocomplete="new-password"')}${field('하루 요약 시간 (한국 시간)', 'digest_time', 'time', 'required value="21:00"')}<p class="form-error" role="alert"></p><button type="submit" class="button primary full">새 가족방 만들기${icon('plus')}</button></form></section>
    <section class="panel"><span class="empty-icon sage">${icon('people')}</span><h2>초대받은 가족방에 참여</h2><p class="muted">초대코드와 가족방 비밀번호를 입력해 주세요.</p><form data-form="lookup-room">${field('초대코드', 'invite_code', 'text', 'required maxlength="8" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="6자리 초대코드"')}${field('가족방 비밀번호', 'password', 'password', 'required maxlength="128" autocomplete="off"')}<p class="form-error" role="alert"></p><button type="submit" class="button secondary full">가족방 확인하기${icon('arrow')}</button></form><div id="join-panel"></div></section></div>`;
}

function renderJoinPreview(message = '') {
  const { room, draft } = state.lookup;
  const selected = draft.people.find(person => person.id === draft.selectedId);
  const valid = draft.canClaim(draft.selectedId, state.user.gender);
  $('#join-panel').innerHTML = `<div class="join-preview"><h3>${e(room.name)}</h3><p class="muted">가족을 누른 뒤 관계를 골라 추가하세요. 내 빈자리를 선택하면 아래 버튼으로 참여할 수 있어요.</p>
    ${message ? errorBlock(message) : ''}${treeMarkup(draft, { editable: true, gender: state.user.gender, userId: state.user.user_id })}
    <div class="tree-join-footer"><p class="tree-selection" role="status">${valid ? `선택한 내 자리: ${e(selected.name || state.user.name)}` : '성별이 맞는 빈자리를 선택해 주세요. 가입한 가족은 선택할 수 없어요.'}</p>
    <div class="button-row">${button('undo-tree', '마지막 추가 취소', '', 'button secondary', draft.additions.length ? '' : 'disabled')}${button('reload-tree', '처음부터 다시', 'refresh', 'button quiet')}</div>
    <form data-form="join-room"><input type="hidden" name="person_id" value="${e(draft.selectedId || '')}"><p class="form-error" role="alert"></p><button type="submit" class="button primary full" ${valid ? '' : 'disabled'}>이 자리로 가족방에 참여하기${icon('arrow')}</button></form></div></div>`;
  mountTree($('#join-panel .family-tree-board'), draft, {
    editable: true,
    onPerson(id) { draft.focusedId = id; if (draft.canClaim(id, state.user.gender)) draft.selectedId = id; renderJoinPreview(); },
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
  applyScreenMode();
  const tabs = elder ? [['feed', 'home', '소식'], ['digest', 'calendar', '오늘 하루'], ['search', 'search', '가족 추억']] : nav;
  const bottom = tabs.map(([key, symbol, label]) => `<a href="#/${key}" data-nav="${key}">${icon(symbol)}<span>${label}</span></a>`).join('');
  app.innerHTML = `<div class="app-layout screen-layout"><div class="workspace"><header class="topbar">${brand()}<div class="current-family">${e(state.room.name)}</div>${elder ? button('elder-help', '도움말', '', 'button quiet compact elder-help', 'aria-label="도움말 보기"') : ''}<a class="icon-button" href="#/settings" aria-label="설정으로 이동">${icon('settings')}</a></header><main id="main" tabindex="-1"><div id="page"></div></main><nav class="screen-bottom" aria-label="주 메뉴">${bottom}</nav></div></div>`;
  window.scrollTo(0, 0);
}

function pageHeading(eyebrow, title, text, controls = '') {
  return `<header class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="muted">${text}</p></div>${controls}</header>`;
}
function currentRoute() { const route = location.hash.replace(/^#\/?/, '').split('?')[0]; return ['feed', 'search', 'digest', 'family', 'settings', 'rooms'].includes(route) ? route : 'feed'; }
async function renderPage() {
  stopReplyCheck(); help.dialog?.close(); endTabTour();
  if (elderRecording && recorder) stopRecording(true);
  elderRecording = false;
  if (!state.room || !state.user) return;
  assistant.refresh();
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
    if (route === 'rooms') {
      page.innerHTML = loading('가족방을 불러오고 있어요');
      const { rooms } = await api('families/');
      if (version !== state.pageVersion) return;
      state.rooms = rooms;
      renderRooms();
    }
  } catch (error) {
    if (version === state.pageVersion) page.innerHTML = failureBlock(error, button('refresh-page', '다시 불러오기', 'refresh'));
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
    <p class="rail-caption">${icon('leaf')}평범한 하루도, 함께라서 특별하니까.</p></aside>`;
}
async function renderFeed(version) {
  $('#page').innerHTML = `<section class="vertical-feed" aria-label="가족 소식">${elder ? button('compose', '가족에게 소식 남기기', 'plus', 'button primary full elder-compose') : ''}<div class="feed-toolbar"><h2>가족의 소식 <span id="post-count"></span></h2>${elder ? '' : button('compose', '소식 쓰기', 'plus', 'button quiet compact')}</div><div id="feed-list">${loading('가족의 이야기를 가져오고 있어요')}</div></section>`;
  const entry = document.createElement('div');
  entry.id = 'daily-entry'; entry.innerHTML = questionEntry(dailyStatus);
  $('.vertical-feed').before(entry);
  const result = await api('posts/');
  if (version !== state.pageVersion) return;
  state.posts = result.posts;
  dailyStatus = result.daily_question || null;
  updateDailyEntry();
  if (!dailyStatus?.title) api('daily-questions/today/').then(question => {
    if (version === state.pageVersion) { dailyStatus = question; updateDailyEntry(); }
  }).catch(() => { /* The entry remains available for an explicit retry. */ });
  updateFeed(); maybeShowHelp(); scheduleReplyCheck();
}

function dailySeenKey() { return `talkdock.web.dailySeen:${state.user?.user_id}:${state.room?.id}`; }
function updateDailyEntry() {
  const target = $('#daily-entry');
  if (!target) return;
  const question = dailyStatus?.date === today() ? dailyStatus : null;
  let seen;
  try { seen = localStorage.getItem(dailySeenKey()); } catch { /* Reading remains available without storage. */ }
  target.innerHTML = questionEntry(question, question ? seen !== questionVersion(question) : false);
}
function markDailySeen(question) {
  if (question.date !== today()) return;
  dailyStatus = question;
  try { localStorage.setItem(dailySeenKey(), questionVersion(question)); } catch { /* Optional unread state. */ }
  updateDailyEntry();
}
function dailyDraftKey() { return `${state.user?.user_id}:${state.room?.id}:${dailyQuestion?.id}`; }
function captureDailyDraft() {
  if (!dailyQuestion || !dailyDraft) return;
  const form = $('[data-form="daily-answer"]', modal);
  if (form) {
    const values = Object.fromEntries(new FormData(form));
    dailyDraft.choice = values.choice || '';
    // Keep the custom draft when another option temporarily hides its field.
    dailyDraft.other_text = form.elements.namedItem('other_text')?.value || '';
    dailyDraft.text = values.text || '';
    dailyDraft.tiers = Object.fromEntries(dailyQuestion.options.map((option, index) => [option, values[`tier-${index}`] || '']));
  }
  const comment = $('[data-form="daily-comment"] textarea', modal);
  if (comment) dailyDraft.comment = comment.value;
  dailyDrafts.set(dailyDraftKey(), { ...dailyDraft });
}
function renderDailyQuestion() {
  const target = $('#daily-content', modal);
  if (target && dailyQuestion) target.innerHTML = questionMarkup(dailyQuestion, state.user.user_id, {
    editing: dailyDraft.editing, draft: dailyDraft, comment: dailyDraft.comment,
  });
}
async function openDailyQuestion() {
  openModal(`${modalHeading('오늘의 질문', 'A LITTLE CONVERSATION')}<div id="daily-content"></div>`, 'daily-dialog');
  await loadDailyQuestion();
}
async function loadDailyQuestion(id) {
  captureDailyDraft();
  const version = ++dailyRequest;
  dailyQuestion = null; dailyDraft = null;
  $('#daily-content', modal).innerHTML = loading('가족과 나눌 질문을 가져오고 있어요');
  try {
    const question = await api(`daily-questions/${id ? `${id}/` : 'today/'}`);
    if (version !== dailyRequest || !modal.open) return;
    dailyQuestion = question;
    const mine = question.answers.find(answer => answer.author_id === state.user.user_id);
    dailyDraft = dailyDrafts.get(dailyDraftKey()) || { ...mine, editing: !mine, comment: '' };
    renderDailyQuestion(); markDailySeen(question);
  } catch (error) {
    if (version === dailyRequest && modal.open) $('#daily-content', modal).innerHTML = failureBlock(error,
      button(id ? 'daily-detail' : 'daily-today', '다시 불러오기', 'refresh', 'button secondary', id ? `data-id="${Number(id)}"` : ''));
  }
}
async function loadDailyHistory(before = null) {
  captureDailyDraft();
  const version = ++dailyRequest;
  dailyQuestion = null; dailyDraft = null;
  const target = $('#daily-content', modal);
  if (!before) { dailyHistoryRows = []; target.innerHTML = loading('지난 질문을 가져오고 있어요'); }
  try {
    const result = await api(`daily-questions/history/${before ? `?before=${encodeURIComponent(before)}` : ''}`);
    if (version !== dailyRequest || !modal.open) return;
    dailyHistoryRows.push(...result.questions);
    target.innerHTML = questionHistory(dailyHistoryRows, result.next_before);
  } catch (error) {
    if (version !== dailyRequest || !modal.open) return;
    if (before) throw error;
    target.innerHTML = failureBlock(error, button('daily-history', '다시 불러오기', 'refresh'));
  }
}
function memoryPostCard(post) {
  const photos = post.images || [];
  return `<article class="post-card" data-post-id="${post.id}"><header class="post-author">${avatar(post.author_name, post.author_id)}<div><strong>${e(post.author_name)}</strong><span class="relationship">${e(post.relationship)}</span><time datetime="${e(post.created_at)}">${dateLabel(post.created_at, true)}</time></div><span class="family-only">가족에게만</span></header>
    ${photos.length ? `<button type="button" class="post-photo" data-action="open-post" data-id="${post.id}" aria-label="${e(post.author_name)}님의 사진과 소식 보기"><img data-post="${post.id}" data-photo-url="${e(photos[0].url)}" alt="${e(post.author_name)}님이 공유한 사진" loading="lazy">${photos.length > 1 ? `<span class="photo-count">${icon('photo')}${photos.length}</span>` : ''}</button>` : ''}
    <div class="post-body"><p class="post-caption">${e(post.caption)}</p></div><footer class="post-actions">${button('open-post', `댓글 <span>${post.comment_count}</span>`, 'comment', 'button quiet', `data-id="${post.id}"`)}${button('post-summary', 'AI로 소식 읽기', 'sparkle', 'button quiet ai-link', `data-id="${post.id}"`)}</footer></article>`;
}
function inlineCommentMarkup(comments) {
  return comments.length ? comments.map(item => `<article class="comment">${avatar(item.author_name, item.id, 'small')}<div><strong>${e(item.author_name)}</strong><span class="relationship">${e(item.relationship)}</span><p>${e(item.text)}</p></div></article>`).join('') : '<p class="no-comments">첫 댓글을 남겨 주세요.</p>';
}
function postCard(post) {
  const photos = post.images || [];
  const more = !elder && Boolean(post.caption?.trim()) && !expandedPosts.has(post.id);
  const actions = `<footer class="post-actions">${button(elder ? 'elder-comment' : 'feed-comments', elder ? '댓글 달기' : '<span class="sr-only">댓글</span>', 'comment', 'button quiet', `data-id="${post.id}" aria-label="${elder ? '댓글 달기' : `댓글 ${post.comment_count}`}"`)}${elder ? '' : button('feed-voice', '<span class="sr-only">말로 댓글</span>', 'mic', 'button quiet', `data-id="${post.id}" aria-label="말로 댓글"`)}${button('feed-listen', feedListenLabel(), 'volume', 'button quiet ai-link', `data-id="${post.id}" aria-label="소식 듣기"`)}</footer>`;
  const caption = `<div class="post-body"><p class="post-caption${more ? ' caption-clamped' : ''}">${e(post.caption)}</p>${more ? button('expand-post', '더보기', null, 'button quiet compact', `data-id="${post.id}" hidden`) : ''}</div>`;
  return `<article class="post-card" data-post-id="${post.id}"><header class="post-author">${avatar(post.author_name, post.author_id)}<div><strong>${e(post.author_name)}</strong><span class="relationship">${e(post.relationship)}</span><time datetime="${e(post.created_at)}">${dateLabel(post.created_at, true)}</time></div></header>
    ${photos.length ? `<button type="button" class="post-photo" data-action="open-post" data-id="${post.id}" aria-label="${e(post.author_name)}님의 사진과 소식 보기"><img data-post="${post.id}" data-photo-url="${e(photos[0].url)}" alt="${e(post.author_name)}님이 공유한 사진" loading="lazy">${photos.length > 1 ? `<span class="photo-count">${icon('photo')}${photos.length}</span>` : ''}</button>` : ''}
    ${elder ? caption + actions : actions + caption}
    ${elder ? `<section class="feed-inline-comments" aria-label="${e(post.author_name)}님의 소식에 달린 댓글" data-comments="${post.id}"><h3>가족의 댓글</h3><div>${inlineComments.has(post.id) ? inlineCommentMarkup(inlineComments.get(post.id)) : '<p class="muted">댓글을 불러올게요.</p>'}</div></section>` : ''}</article>`;
}
/** Elderly feed: replying happens inside the card, without opening the post dialog. */
function elderReplyMarkup(post) {
  return `<section class="elder-reply" data-reply="${post.id}" aria-label="${e(post.author_name)}님에게 답장"><div class="elder-reply-heading"><h3>${e(post.author_name)}님에게 답장</h3>${button('elder-reply-close', '<span class="sr-only">답장 닫기</span>', 'close', 'icon-button', `data-id="${post.id}" aria-label="답장 닫기"`)}</div><div class="elder-reply-voice">${elderVoiceIdle(post.id)}</div><form data-form="elder-reply" data-id="${post.id}"><label class="field"><span>글로 쓰셔도 돼요</span><textarea name="text" rows="3" maxlength="2000" placeholder="하고 싶은 말씀을 적어보세요"></textarea></label><p class="form-error" role="alert"></p><button type="submit" class="button secondary">댓글 보내기</button></form></section>`;
}
function elderVoiceIdle(id) { return button('elder-reply-record', '말로 답하기', 'mic', 'button primary full', `data-id="${id}"`); }
function closeElderReply(panel) {
  if (!panel) return;
  if (elderRecording && recorder) stopRecording(true);
  elderRecording = false;
  panel.remove();
}
function toggleElderReply(id) {
  const card = document.querySelector(`#feed-list .post-card[data-post-id="${id}"]`), post = state.posts.find(item => item.id === id);
  if (!card || !post) return;
  const open = card.querySelector('.elder-reply');
  document.querySelectorAll('#feed-list .elder-reply').forEach(closeElderReply);
  if (open) return;
  // Replying moves on from listening: stop it and fold away the summary shown above.
  stopAudio();
  card.querySelectorAll('.feed-audio-summary').forEach(panel => { panel.hidden = true; });
  const comments = card.querySelector('.feed-inline-comments');
  if (comments) comments.insertAdjacentHTML('beforebegin', elderReplyMarkup(post)); else card.insertAdjacentHTML('beforeend', elderReplyMarkup(post));
  if (post.author_id !== state.user.user_id) markGuideSeen(guideKeys().reply);
  restoreDraft(card.querySelector('.elder-reply textarea'), commentDraft(draftScope(), id));
  card.querySelector('.elder-reply')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
async function reloadInlineComments(id) {
  try {
    const result = await api(`posts/${id}/`);
    inlineComments.set(id, result.comments);
    const post = state.posts.find(item => item.id === id); if (post) post.comment_count = result.comments.length;
    refreshPostComments(id, result.comments);
  } catch { toast('댓글은 등록됐어요. 최신 댓글은 잠시 후 다시 확인해 주세요.'); }
}
function observeInlineComments() {
  if (!elder) return;
  inlineObserver?.disconnect();
  inlineObserver = new IntersectionObserver(entries => entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    inlineObserver.unobserve(entry.target);
    const id = Number(entry.target.dataset.postId);
    const key = `${state.session}:${state.room.id}:${id}`;
    if (!inlineComments.has(id) && !pendingComments.has(key)) { pendingComments.add(key); commentQueue.push({ id, key, session: state.session, room: state.room.id }); drainInlineComments(); }
  }), { rootMargin: '200px' });
  document.querySelectorAll('#feed-list .post-card').forEach(card => inlineObserver.observe(card));
}
function drainInlineComments() {
  while (commentActive < 2 && commentQueue.length) {
    const task = commentQueue.shift();
    if (task.session !== state.session || task.room !== state.room?.id) { pendingComments.delete(task.key); continue; }
    commentActive++;
    api(`posts/${task.id}/`, { room: task.room }).then(post => {
      if (task.session !== state.session || task.room !== state.room?.id) return;
      inlineComments.set(task.id, post.comments);
      const target = document.querySelector(`[data-comments="${task.id}"] > div`);
      if (target) target.innerHTML = inlineCommentMarkup(post.comments);
    }).catch(() => {
      if (task.session !== state.session || task.room !== state.room?.id) return;
      const target = document.querySelector(`[data-comments="${task.id}"] > div`);
      if (target) target.innerHTML = `<p class="muted">댓글을 불러오지 못했어요.</p>${button('retry-comments', '다시 불러오기', 'refresh', 'button quiet compact', `data-id="${task.id}"`)}`;
    }).finally(() => { pendingComments.delete(task.key); commentActive--; drainInlineComments(); });
  }
}

function updateFeed() {
  const posts = state.posts;
  // Re-rendering drops open reply panels; never keep the microphone running behind them.
  if (elderRecording && recorder) stopRecording(true);
  elderRecording = false;
  $('#post-count').textContent = `${posts.length}`;
  $('#feed-list').innerHTML = posts.length ? posts.map(postCard).join('') : empty('heart', '첫 번째 안부를 기다리고 있어요', '사진 한 장도, 짧은 글 한 줄도 좋아요. 가족에게 오늘을 전해 보세요.', button('compose', '첫 소식 남기기', 'plus', 'button primary'));
  observeCaptionOverflow();
  hydrateImages(); observeInlineComments();
  assistant.refresh();
}
function observeCaptionOverflow() {
  captionObserver?.disconnect();
  const sync = caption => {
    const more = caption.parentElement?.querySelector('[data-action="expand-post"]');
    if (more) more.hidden = !captionNeedsMore(caption.scrollHeight, caption.clientHeight, elder);
  };
  captionObserver = new ResizeObserver(entries => entries.forEach(entry => sync(entry.target)));
  document.querySelectorAll('#feed-list .caption-clamped').forEach(caption => { sync(caption); captionObserver.observe(caption); });
  document.fonts.ready.then(() => document.querySelectorAll('#feed-list .caption-clamped').forEach(sync));
}
function feedListenLabel(active = false) {
  const label = active ? '듣기 중지' : '소식 듣기';
  return elder ? label : `<span class="sr-only">${label}</span>`;
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
      <section class="ai-panel"><div class="ai-heading">${icon('sparkle')}<h3>AI와 함께 읽어요</h3></div><p class="help">소식을 쉽게 풀어 읽고, 궁금한 점을 물어보세요.</p><div class="button-row">${button('summary', '소식 요약하기', 'sparkle', 'button secondary compact')}${button('summary-audio', '요약 듣기', 'volume', 'button quiet compact')}</div><div id="summary-result" class="ai-result" aria-live="polite"></div>${button('stop-audio', '듣기 중지', 'stop', 'button quiet compact', 'hidden')}<div id="question-history" class="question-history" aria-live="polite"></div><form data-form="post-question" class="inline-form"><label class="sr-only" for="post-question">이 소식에 대해 물어보기</label><input id="post-question" name="question" maxlength="1000" required placeholder="이 소식에 대해 궁금한 점은?"><button type="submit" class="icon-button send-button" aria-label="AI에게 질문하기">${icon('arrow')}</button><p class="form-error" role="alert"></p></form><p class="fine-print">AI 답변은 실제 소식과 다를 수 있어요. 중요한 내용은 가족에게 확인해 주세요.</p></section>
      <section class="comments-section"><h3>마음을 나눠요 <span id="comment-count">${post.comments.length}</span></h3><div id="comments"></div><form data-form="comment"><label class="sr-only" for="comment-text">가족에게 댓글 남기기</label><textarea id="comment-text" name="text" required maxlength="2000" rows="2" placeholder="다정한 한마디를 남겨보세요."></textarea><p class="form-error" role="alert"></p><div class="comment-submit">${button('record', '음성으로 답장', 'mic', 'button quiet compact')}<button type="submit" class="button primary compact">댓글 보내기${icon('arrow')}</button></div></form><div id="voice-panel" aria-live="polite"></div></section></section></div>`;
    // Keep the reply controls outside the scrolling post and comment history.
    const scroller = document.createElement('div'); scroller.className = 'post-scroll';
    const footer = document.createElement('div'); footer.className = 'post-reply-footer';
    const detail = $('.post-detail', modal); detail.before(scroller); scroller.append(detail);
    footer.append($('form[data-form="comment"]', modal), $('#voice-panel', modal)); modal.append(footer);
    renderComments();
    restoreDraft($('#comment-text', modal), commentDraft(draftScope(), post.id));
    $('#question-history', modal).innerHTML = questionHistoryMarkup();
    if (post.images.length) showPhoto(0);
    hydrateImages(modal);
    if (summarize) await busy($('[data-action="summary"]', modal), () => loadSummary());
  } catch (error) {
    if (version === state.modalVersion) modal.innerHTML = `${modalHeading('소식을 불러오지 못했어요')}${failureBlock(error, button('retry-post', '다시 열기', 'refresh', 'button secondary', `data-id="${id}"`))}`;
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
function audioControl(target, preparing = true) {
  if (!target?.isConnected) return;
  target.hidden = false;
  target.innerHTML = icon('stop') + (preparing ? '취소' : '듣기 중지');
  target.setAttribute('aria-label', preparing ? '음성 준비 취소' : '듣기 중지');
}
/** Elderly screen: after the post is read, gently suggest replying to that family member. Spoken only. */
function spokenPost(text, post) { return elder ? withReplyPrompt(text, replyPrompt(post, state.user?.user_id)) : text; }
async function playSpeech(text, target, valid = () => true, generation = null) {
  if (!text) throw new ApiError('먼저 요약을 불러와 주세요.');
  if (generation === null) { stopAudio(); generation = audioGeneration; }
  if (afterAudio && !afterAudio.generation) afterAudio.generation = generation;
  const current = () => generation === audioGeneration && valid();
  if (!current()) return;
  audioControl(target);
  try {
    const blob = await api('speech/', { method: 'POST', data: { text }, binary: true });
    if (!current()) return;
    audioURL = URL.createObjectURL(blob);
    const player = new Audio(audioURL); audio = player;
    player.addEventListener('ended', () => { if (current()) stopAudio(); }, { once: true });
    player.addEventListener('error', () => { if (current()) { stopAudio(); toast('음성을 재생하지 못했어요. 다시 시도해 주세요.'); } }, { once: true });
    try { await player.play(); }
    catch { if (current()) throw new ApiError('재생이 차단되었어요. 듣기 버튼을 다시 눌러 주세요.'); }
    if (current()) audioControl(target, false);
  } catch (error) { if (current()) { stopAudio(); throw error; } }
}
async function listenToSummary() {
  stopAudio();
  const generation = audioGeneration, version = state.modalVersion;
  const valid = () => generation === audioGeneration && version === state.modalVersion && modal.open;
  const control = $('[data-action="stop-audio"]', modal); audioControl(control);
  try {
    if (!state.detail.summary) await loadSummary();
    if (!valid()) return;
    if (state.detail?.summary) await playSpeech(spokenPost(state.detail.summary, state.detail), control, valid, generation);
    else stopAudio();
  } catch (error) { if (valid()) { stopAudio(); toast(error.message); } }
}

function openComposer() {
  openModal(`${modalHeading('오늘의 안부를 남겨요', 'A LITTLE MOMENT')}<form data-form="post"><div class="composer-user">${avatar(state.user.name, state.user.user_id)}<div><strong>${e(state.user.name)}</strong><p class="help">${e(state.room.name)} 가족에게 공유돼요.</p></div></div><label class="sr-only" for="post-caption">소식 내용</label><textarea id="post-caption" name="caption" maxlength="2000" rows="5" placeholder="오늘 있었던 일, 가족과 나누고 싶은 순간을 들려주세요."></textarea><div class="character-count"><span id="caption-count">0</span> / 2,000</div><button type="button" data-action="record-post" class="button secondary">${icon('mic')}말로 쓰기</button><div id="voice-panel" aria-live="polite"></div><label class="upload-zone" id="drop-zone" tabindex="0">${icon('photo')}<strong>사진을 여기에 놓거나 클릭해 주세요</strong><span>최대 5장 · 사진 없이 글만 써도 좋아요</span><input id="photo-input" type="file" accept="image/jpeg,image/png,image/webp,image/gif,image/bmp" multiple class="sr-only"></label><div id="photo-previews" class="photo-previews"></div><p class="form-error" role="alert"></p><div class="composer-footer"><p class="help">${icon('heart')}작은 안부가 가족에게 큰 기쁨이 돼요.</p><button type="submit" class="button primary">소식 전하기${icon('arrow')}</button></div></form>`, 'compose-dialog');
  // Text written earlier in this browser is kept until it is published (photos are not kept).
  if (restoreDraft($('#post-caption'), postDraft(draftScope()))) toast('임시 저장한 글을 불러왔어요.');
}
function addFiles(files) {
  const next = [...state.files, ...files];
  if (next.length > 5) return toast('사진은 최대 5장까지 선택할 수 있어요.');
  if (next.some(file => !/^image\/(jpeg|png|webp|gif|bmp)$/.test(file.type))) return toast('JPG, PNG, WebP, GIF, BMP 사진을 선택해 주세요.');
  state.files = next;
  renderPreviews();
}
function renderPreviews() {
  previewURLs.forEach(url => URL.revokeObjectURL(url));
  previewURLs = state.files.map(file => URL.createObjectURL(file));
  $('#photo-previews').innerHTML = state.files.map((file, index) => `<div class="preview"><img src="${previewURLs[index]}" alt="${e(file.name)}"><button type="button" data-action="remove-photo" data-index="${index}" class="icon-button" aria-label="${e(file.name)} 제외">${icon('close')}</button><span>${e(file.name)}</span></div>`).join('');
}

/**
 * Three elderly memory examples. The first names the family member who posted most recently,
 * by the viewer-side relationship the server already resolved (or their name when that is generic).
 */
function memoryExamples() {
  const generic = new Set(['가족', '인척', '공동 부모 쪽 가족']);
  const subject = state.posts.map(post => {
    const relation = (post.relationship || '').trim(), name = (post.author_name || '').trim();
    if (post.author_id === state.user?.user_id || relation === '나' || relation === '오늘의 질문') return null;
    return relation && !generic.has(relation) ? relation : name || null;
  }).find(Boolean);
  const first = subject ? `${subject}${topicParticle(subject)} 요즘 어떻게 지내?` : '가족들은 요즘 어떻게 지내?';
  return [first, '지난 명절에 가족끼리 뭐 했었지?', '최근에 가족 중에 생일이나 기념일이 있었어?'];
}
/** 은/는 by the final consonant of the last Hangul syllable. */
function topicParticle(word) {
  const code = word.charCodeAt(word.length - 1) - 0xAC00;
  return code >= 0 && code < 11172 && code % 28 ? '은' : '는';
}
/**
 * Elderly tabs run a short hands-on tour once, on the first visit: a hand points at the real button
 * and each step moves on when that button is pressed.
 */
let tabTour = null, tourTarget = null, tourHand = null, tourFrame = 0;
const TAB_TOUR = {
  'day-listen': ['이야기 듣기를 누르면 가족의 하루를 들려 드려요.', '[data-action="digest-audio"]'],
  'day-previous': ['◀ 전날을 누르면 지난 날의 이야기도 볼 수 있어요.', '[data-action="elder-day-step"][data-step="-1"]'],
  'memory-example': ['예시 질문을 누르면 바로 가족의 추억을 찾아 드려요.', '[data-action="memory-example"]'],
  'memory-listen': ['답변이 나오면 답변 듣기를 눌러 찾은 답을 들어 보세요.', '[data-action="memory-audio"]'],
  'memory-voice': ['다음에는 말로 물어보기를 누르고 궁금한 것을 직접 말씀해 보세요.', '[data-action="memory-voice"]'],
};
function startTabTour(tab) {
  if (!elder || !state.user) return false;
  const key = `${guideKeys().basic}:tab:${tab}`;
  if (guideSeen(key)) return false;
  markGuideSeen(key);
  return true;
}
function tourStep(step) {
  tabTour = step;
  const [text, selector] = TAB_TOUR[step];
  let box = $('#page .tab-hint');
  if (!box) {
    $('#page').insertAdjacentHTML('afterbegin', `<aside class="tab-hint" role="status" aria-live="polite"><p></p>${button('tab-hint-close', '안내 닫기', '', 'button quiet compact')}</aside>`);
    box = $('#page .tab-hint');
  }
  $('p', box).textContent = text;
  pointAt($(selector));
}
function endTabTour() { tabTour = null; $('#page .tab-hint')?.remove(); pointAt(null); }
function pointAt(target) {
  cancelAnimationFrame(tourFrame);
  tourTarget?.classList.remove('tour-target'); tourTarget = target || null;
  if (!target) { tourHand?.remove(); tourHand = null; return; }
  target.classList.add('tour-target');
  if (!tourHand) {
    tourHand = document.createElement('span'); tourHand.className = 'tour-hand'; tourHand.setAttribute('aria-hidden', 'true');
    tourHand.innerHTML = '<img src="/web/assets/assistant_character.png" alt=""><span>👆</span>';
    document.body.append(tourHand);
  }
  target.scrollIntoView({ block: 'center', behavior: 'smooth' });
  const follow = () => {
    if (!tourTarget?.isConnected) { pointAt(null); return; }
    const rect = tourTarget.getBoundingClientRect();
    tourHand.style.left = `${Math.round(rect.right - 56)}px`; tourHand.style.top = `${Math.round(rect.bottom - 18)}px`;
    tourFrame = requestAnimationFrame(follow);
  };
  follow();
}
function memoryVoiceIdle(message = '') {
  return `${button('memory-voice', '말로 물어보기', 'mic', 'button primary full')}${message ? `<p class="form-error" role="alert">${e(message)}</p>` : ''}`;
}
function renderSearch() {
  $('#page').innerHTML = `${pageHeading('MEMORIES TOGETHER', '함께 쌓아온 추억 찾기', '기억이 가물가물한 순간, 가족의 이야기 속에서 함께 찾아봐요.')}<section class="search-hero panel"><span class="empty-icon sage">${icon('search')}</span><h2>우리 가족의 어떤 순간이 궁금하세요?</h2><p class="muted">가족이 남긴 소식을 바탕으로 AI가 추억을 찾아드려요.</p>${elder ? `<div class="memory-examples"><div class="memory-voice" aria-live="polite">${memoryVoiceIdle()}</div><h3>이렇게 물어보세요</h3>${memoryExamples().map(q => button('memory-example', e(q), '', 'button secondary full', `data-question="${e(q)}"`)).join('')}<p class="muted">글로 물어보셔도 돼요</p></div>` : ''}<form data-form="search" class="memory-search"><label class="sr-only" for="memory-question">가족 기록에서 찾을 내용</label><input id="memory-question" name="question" required maxlength="1000" placeholder="예: 지난번 가족 여행은 어디로 갔었지?"><button class="button primary" type="submit">추억 찾기${icon('arrow')}</button><p class="form-error" role="alert"></p></form><div id="memory-past">${pastMemoriesMarkup(memorySearches(draftScope()), e)}</div></section><div id="search-result" aria-live="polite"></div><p class="page-note">${icon('leaf')}AI는 저장된 가족 기록을 참고해요. 아직 정리되지 않은 소식은 검색되지 않을 수 있어요.</p>`;
  if (startTabTour('search')) tourStep('memory-example');
}
async function renderDigest(version) {
  selectedDigestDate ||= today(); digestMonth ||= new Date(`${selectedDigestDate.slice(0, 7)}-01T00:00:00Z`);
  if (elder) {
    $('#page').innerHTML = `<section class="day-page elder-day"><h1>우리 가족의 하루</h1><p class="muted">가족이 보낸 하루 이야기를 들어 보세요.</p><input id="digest-date" type="date" value="${selectedDigestDate}" max="${today()}" hidden><div class="elder-day-steps">${button('elder-day-step', '◀ 전날', '', 'button secondary', 'data-step="-1" aria-label="전날 이야기"')}${button('elder-day-step', '다음 날 ▶', '', 'button secondary', `data-step="1" aria-label="다음 날 이야기" ${selectedDigestDate >= today() ? 'disabled' : ''}`)}</div><div id="digest-result" aria-live="polite"></div></section>`;
    await loadDigest(selectedDigestDate, false, version);
    if (version === state.pageVersion && startTabTour('digest')) tourStep($('[data-action="digest-audio"]') ? 'day-listen' : 'day-previous');
    return;
  }
  $('#page').innerHTML = `<section class="day-page"><h1>우리 가족의 하루</h1><p class="muted">달력에서 함께한 날을 골라 보세요.</p><input id="digest-date" type="date" value="${selectedDigestDate}" max="${today()}" hidden><section class="panel month-calendar" aria-label="날짜 선택"><div class="month-heading">${button('day-prev', '<span class="sr-only">이전 달</span>', 'chevron', 'icon-button previous-month')}<h2 id="month-title"></h2>${button('day-next', '<span class="sr-only">다음 달</span>', 'chevron', 'icon-button')}</div><div class="month-weekdays" aria-hidden="true">${['일','월','화','수','목','금','토'].map(day=>`<span>${day}</span>`).join('')}</div><div id="month-grid" class="month-grid"></div></section><section id="digest-result" aria-live="polite">${loading('이날의 소식을 가져오고 있어요')}</section></section>`;
  renderMonth();
  api('digests/history/').then(result => { if (version === state.pageVersion) { digestDates = result.dates; renderMonth(); } }).catch(() => {});
  await loadDigest(selectedDigestDate, false, version);
}
function renderMonth() {
  if (!$('#month-grid')) return;
  const year=digestMonth.getUTCFullYear(), month=digestMonth.getUTCMonth();
  $('#month-title').textContent=`${year}년 ${month+1}월`;
  $('[data-action="day-next"]').disabled = `${year}-${String(month+1).padStart(2,'0')}` >= today().slice(0,7);
  $('#month-grid').innerHTML=calendarDays(year,month).map(day=>{
    if (!day) return '<span></span>';
    const date=`${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
    return `<button type="button" data-action="digest-date" data-date="${date}" aria-label="${month+1}월 ${day}일" aria-pressed="${date===selectedDigestDate}" class="month-day${digestDates.includes(date)?' has-news':''}" ${date>today()?'disabled':''}>${day}</button>`;
  }).join('');
}
async function loadDigest(date, retry = false, version = state.pageVersion) {
  if (!date) return;
  selectedDigestDate=date; const requestId=Symbol(); state.digestRequest=requestId;
  renderMonth(); $('#digest-result').innerHTML=loading('이날의 이야기를 가져오고 있어요');
  try {
    const result=await api(`digests/${retry?'':`?date=${encodeURIComponent(date)}`}`,retry?{method:'POST',data:{date}}:{});
    let posts=result.posts;
    if (!posts) {
      const result = await api('posts/');
      posts=result.posts.filter(post=>koreanDay(post.created_at)===date);
    }
    if (version!==state.pageVersion || state.digestRequest!==requestId) return;
    state.digest={...result,posts};
    const pictures=posts.map(post=>`<button type="button" class="day-photo" data-action="open-post" data-id="${post.id}" aria-label="${e(post.author_name)}님의 소식 보기">${post.images?.[0]?`<img data-post="${post.id}" data-photo-url="${e(post.images[0].url)}" alt="${e(post.author_name)}님의 사진">`:`<span>${icon('text')}<span class="sr-only">글로 전한 소식</span></span>`}</button>`).join('');
    $('#digest-result').innerHTML=`<h2>${e(dateLabel(date+'T12:00:00+09:00'))}의 소식 ${posts.length}개</h2>${posts.length?`<div class="day-photos">${pictures}</div>`:empty('leaf','이날은 아직 올라온 소식이 없어요','다른 날짜를 골라보세요.')}<div class="day-actions">${button('digest-story','오늘 이야기 보기','book','button secondary full')}${button('digest-audio','오늘 이야기 듣기','volume','button secondary full',result.status==='ready'?'':'disabled')}${button('stop-audio','듣기 중지','stop','button quiet','hidden')}</div>${result.status!=='ready'?`<p class="help">${result.status==='pending'?`${e(result.digest_time||state.room.digest_time)}에 하루 요약이 도착해요.`:result.status==='processing'?'하루 요약을 준비하고 있어요.':result.status==='failed'?'하루 요약을 준비하지 못했어요.':'소식이 모이면 하루 이야기를 들을 수 있어요.'}</p>${['failed','processing'].includes(result.status)?button('retry-digest','다시 준비하기','refresh','button quiet'):''}`:''}`;
    if (elder) $('#digest-result').innerHTML = elderDayMarkup(date, result, pictures, posts.length);
    hydrateImages($('#digest-result'));
  } catch(error) { if (version===state.pageVersion && state.digestRequest===requestId) $('#digest-result').innerHTML=failureBlock(error,button('retry-digest','다시 불러오기','refresh')); }
}
function elderDayMarkup(date, result, pictures, count) {
  const day = date === today() ? '오늘' : dateLabel(date + 'T12:00:00+09:00');
  const ready = result.status === 'ready';
  const waiting = result.status === 'pending' ? `오늘 ${e(result.digest_time || state.room.digest_time)}에 하루 이야기가 도착해요.` : result.status === 'empty' ? '이날은 가족이 남긴 소식이 없어요.' : '하루 이야기가 준비되면 들을 수 있어요.';
  return `<h2 class="elder-day-title">${e(day)}의 이야기</h2><div class="day-actions">${ready ? `${button('digest-audio', `${e(day)} 이야기 듣기`, 'volume', 'button primary full')}${button('stop-audio', '듣기 중지', 'stop', 'button quiet', 'hidden')}` : `<p class="help">${waiting}</p>`}${button('digest-story', '글로 읽기', 'book', 'button secondary full')}</div>${count ? `<h3>${e(day)} 올라온 소식 ${count}개</h3><div class="day-photos">${pictures}</div>` : ''}`;
}
function showDigestStory() {
  const digest=state.digest;if(!digest)return;
  const pictures=digest.posts.map(post=>`<button type="button" class="day-photo" data-action="open-post" data-id="${post.id}" aria-label="${e(post.author_name)}님의 소식 보기">${post.images?.[0]?`<img data-post="${post.id}" data-photo-url="${e(post.images[0].url)}" alt="${e(post.author_name)}님의 사진">`:icon('text')}</button>`).join('');
  openModal(`${modalHeading('오늘도, 함께')}<p class="muted">${e(digest.date)} · 이날의 소식 ${digest.posts.length}개</p><div class="day-photos">${pictures}</div>${digest.status==='ready'?`<p class="digest-text">${e(digest.text)}</p>`:`<p class="help">${digest.status==='pending'?'하루 요약이 도착할 시간을 기다리고 있어요.':digest.status==='empty'?'이날은 아직 올라온 소식이 없어요.':'하루 요약을 아직 준비하지 못했어요. 하루 화면에서 다시 확인해 주세요.'}</p>`}`,'day-story-dialog');
  hydrateImages(modal);
}
function refreshPostComments(id, comments) {
  const card=document.querySelector(`#feed-list .post-card[data-post-id="${id}"]`);if(!card)return;
  const action=card.querySelector('[data-action="feed-comments"]');if(action)action.setAttribute('aria-label',`댓글 ${comments.length}`);
  const target=card.querySelector('.feed-inline-comments > div');if(target)target.innerHTML=inlineCommentMarkup(comments);
}
async function listenToPost(id, target) {
  stopAudio();
  // Listening moves on from replying: close any reply area left open in the feed.
  document.querySelectorAll('#feed-list .elder-reply').forEach(closeElderReply);
  const generation = audioGeneration, session = state.session, room = state.room.id, version = state.pageVersion;
  const valid = () => generation === audioGeneration && session === state.session && room === state.room?.id && version === state.pageVersion;
  const card = target.closest('.post-card') || document.querySelector(`#feed-list .post-card[data-post-id="${id}"]`);
  if (!card) return;
  let panel = card.querySelector('.feed-audio-summary');
  if (!panel) {
    panel = document.createElement('section'); panel.className = 'feed-audio-summary';
    // Elderly cards read top to bottom: what was heard, the reply, then the family's comments.
    const anchor = elder && (card.querySelector('.elder-reply') || card.querySelector('.feed-inline-comments'));
    if (anchor) anchor.before(panel); else card.append(panel);
  }
  panel.hidden = false; panel.dataset.preparing = 'true';
  panel.innerHTML = `<p aria-live="polite">요약을 준비하고 있어요.</p>${button('stop-audio', '취소', 'stop', 'button quiet compact')}${elder ? `<div class="feed-ask" hidden><p class="feed-ask-hint">이 소식 관련해서 궁금한 점을 토닥이에게 물어보세요!</p>${button('post-ask', '소식 물어보기', 'sparkle', 'button primary full', `data-id="${id}"`)}</div>` : ''}`;
  // Elderly screen: after listening, questions about this post start right here.
  const showAsk = () => { const ask = $('.feed-ask', panel); if (ask) ask.hidden = false; };
  const control = $('[data-action="stop-audio"]', panel); audioControl(control);
  target.dataset.action = 'feed-stop-listen'; target.innerHTML = icon('stop') + '취소'; target.setAttribute('aria-label', '음성 준비 취소');
  const post = state.posts.find(item => item.id === id), caption = post?.caption?.trim();
  let summarized = false;
  try {
    const result = await api(`posts/${id}/message/`, { method:'POST', room });
    if (!valid()) return;
    if (result.status !== 'ready') throw new ApiError(result.status === 'failed' ? '소식을 읽을 준비를 하지 못했어요. 다시 시도해 주세요.' : '소식을 읽을 준비 중이에요. 잠시 후 다시 눌러 주세요.');
    summarized = true;
    delete panel.dataset.preparing; $('p', panel).textContent = result.text; showAsk();
    await playSpeech(spokenPost(result.text, post), control, valid, generation);
    if (valid() && audio && !audio.paused) { target.innerHTML = icon('stop') + feedListenLabel(true); target.setAttribute('aria-label','듣기 중지'); }
  } catch (error) {
    if (!valid()) return;
    delete panel.dataset.preparing;
    // One tap should always speak in the elderly screen: read the family's own words instead.
    if (elder && !summarized && caption && error.status !== 401) {
      $('p', panel).textContent = '요약 대신 가족이 쓴 글을 읽어 드려요.'; showAsk();
      try {
        await playSpeech(spokenPost(caption, post), control, valid, generation);
        if (valid() && audio && !audio.paused) { target.innerHTML = icon('stop') + feedListenLabel(true); target.setAttribute('aria-label','듣기 중지'); }
      } catch (speechError) { if (valid()) { $('p', panel).textContent = speechError.message; stopAudio(); } }
      return;
    }
    $('p', panel).textContent = error.message; stopAudio();
  }
}

function renderFamily() {
  const owner = state.room.members.some(member => member.id === state.user.user_id && member.is_owner);
  $('#page').innerHTML = `${pageHeading('CLOSER, TOGETHER', '우리 가족', '가족의 연결을 가계도에서 살펴보세요.', button('refresh-page', '가계도 새로고침', 'refresh'))}<div class="family-layout"><section class="panel"><div class="section-heading"><div><p class="eyebrow">FAMILY ROOM</p><h2>${e(state.room.name)}</h2></div><span class="tag">${state.room.members.length}명의 가족</span></div>${treeMarkup(new FamilyTreeDraft(state.room.tree), { userId: state.user.user_id, members: state.room.members })}<p class="help">가입한 가족 ${state.room.members.length}명 · 가계도 속 사람 ${state.room.tree.people.length}명</p></section><aside><section class="panel invitation-card"><span class="empty-icon">${icon('heart')}</span><h2>가족을 초대해 보세요</h2><p class="muted">초대코드와 가족방 비밀번호를<br>가족에게 함께 알려주세요.</p><div class="invite-code">${e(state.room.invite_code)}</div>${button('copy-code', '초대코드 복사', 'copy', 'button secondary full')}<p class="help">참여할 때, 가계도에서 내 자리를 선택해 주세요.</p></section><section class="panel digest-settings"><h2>${icon('calendar')}하루 요약 시간</h2>${owner ? `<form data-form="digest-time">${field('매일, 한국 시간 기준', 'digest_time', 'time', `value="${e(state.room.digest_time)}" required`)}<p class="form-error" role="alert"></p><button type="submit" class="button secondary full">시간 저장하기</button></form>` : `<strong class="time-display">${e(state.room.digest_time)}</strong><p class="help">가족방을 만든 사람이 변경할 수 있어요.</p>`}</section></aside></div>`;
  mountTree($('#page .family-tree-board'), new FamilyTreeDraft(state.room.tree));
}
function renderSettings() {
  $('#page').innerHTML = `${pageHeading('YOUR LITTLE SPACE', '계정 설정', '가족에게 보여줄 내 정보를 관리해요.')}<div class="settings-grid"><section class="panel"><h2>내 프로필</h2><div class="settings-profile">${avatar(state.user.name, state.user.user_id, 'large')}<div><strong>${e(state.user.name)}</strong><p class="muted">@${e(state.user.username)}</p></div></div><form data-form="profile">${field('가족에게 보여줄 이름', 'name', 'text', `value="${e(state.user.name)}" maxlength="40" required autocomplete="name"`)}<p class="form-error" role="alert"></p><button class="button primary" type="submit">이름 저장하기</button></form></section><section class="panel" data-voice-field hidden><h2>읽어 주는 목소리</h2><p class="muted">소식과 요약을 들을 때 사용할 목소리를 골라요.</p><form data-form="voice"><label class="field"><span>목소리</span><select name="tts_voice"></select></label><button type="button" class="button quiet compact" data-voice-sample hidden></button><p class="form-error" role="alert"></p><button class="button secondary" type="submit">목소리 저장하기</button></form></section><section class="panel"><h2>비밀번호 변경</h2><p class="muted">변경하면 다른 기기의 로그인은 해제돼요.</p><form data-form="password">${field('현재 비밀번호', 'current_password', 'password', 'required maxlength="128" autocomplete="current-password"')}${field('새 비밀번호', 'new_password', 'password', 'required minlength="10" maxlength="128" autocomplete="new-password"')}${field('새 비밀번호 확인', 'confirm_password', 'password', 'required minlength="10" maxlength="128" autocomplete="new-password"')}<p class="help">숫자를 포함한 10자 이상. 아이디·이름과 비슷하거나 흔한 값은 피해주세요.</p><p class="form-error" role="alert"></p><button class="button secondary" type="submit">비밀번호 변경하기</button></form></section></div>`;
  $('#page').insertAdjacentHTML('afterbegin', `<section class="panel screen-preferences"><h2>화면과 가족방</h2><div class="button-row">${button('screen-standard', '기본 화면', 'home', 'button secondary', `aria-pressed="${!elder}"`)}${button('screen-elder', '어르신 화면', 'people', 'button secondary', `aria-pressed="${elder}"`)}</div><p class="help">어르신 화면은 글과 댓글을 크게 보여줘요. 하루와 추억은 토닥 도우미에서 열 수 있어요.</p><div class="button-row"><a href="#/rooms" class="button quiet">가족방 전환</a>${button('switch-account', '계정 전환', 'people', 'button quiet')}<a href="#/family" class="button quiet">가계도 보기</a>${button('logout', '로그아웃', 'logout', 'button quiet')}</div></section>`);
  fillVoiceSelect($('form[data-form="voice"] select[name="tts_voice"]'), state.user.tts_voice);
}

function stopRecording(discard = false) {
  clearTimeout(recordingTimer);
  if (discard) recordingRequest++;
  const current = recorder, stream = recordingStream;
  recordingStream = null;
  recorder = null;
  if (current && current.state !== 'inactive') {
    if (discard) current.onstop = null;
    current.stop();
  }
  stream?.getTracks().forEach(track => track.stop());
}
async function startRecording({ postId = state.detail?.id, purpose = null, target = null } = {}) {
  const voicePanel = () => target || $('#voice-panel');
  // The in-card reply always keeps a way to record again after a failure.
  const retry = () => purpose === 'elder-reply' ? elderVoiceIdle(postId) : purpose === 'memory' ? memoryVoiceIdle() : '';
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new ApiError('음성 답장은 localhost 또는 HTTPS에서 지원되는 브라우저로 이용해 주세요.');
  if (recorder) return;
  const request = ++recordingRequest;
  const version = state.modalVersion;
  const questionRequest = dailyRequest;
  const valid = () => request === recordingRequest && version === state.modalVersion && (!purpose || purpose === 'post' || questionRequest === dailyRequest);
  const retryAction = purpose === 'post' ? 'record-post' : purpose === 'elder-reply' ? 'elder-reply-record' : purpose === 'memory' ? 'memory-voice' : purpose ? `daily-record-${purpose}` : 'record';
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { if (valid()) throw new ApiError('마이크를 사용할 수 없어요. 브라우저의 마이크 권한과 연결을 확인해 주세요.'); else return; }
  if (!valid()) { stream.getTracks().forEach(track => track.stop()); return; }
  const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
  if (!mimeType) { stream.getTracks().forEach(track => track.stop()); throw new ApiError('이 브라우저의 녹음 형식을 지원하지 않아요. 최신 Chrome 또는 Edge로 이용해 주세요.'); }
  let current;
  try { current = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64000 }); }
  catch { stream.getTracks().forEach(track => track.stop()); throw new ApiError('녹음을 시작하지 못했어요. 마이크 설정을 확인해 주세요.'); }
  recorder = current;
  recordingStream = stream;
  elderRecording = purpose === 'elder-reply' || purpose === 'memory';
  const chunks = [];
  let bytes = 0;
  current.ondataavailable = event => {
    if (!valid()) return;
    chunks.push(event.data); bytes += event.data.size;
    if (bytes > 4.5 * 1024 * 1024 && recorder === current) stopRecording();
  };
  current.onerror = () => {
    if (!valid()) return;
    stopRecording(true);
    voicePanel().innerHTML = errorBlock('녹음 중 문제가 생겼어요. 다시 시도해 주세요.') + retry();
  };
  current.onstop = async () => {
    stream.getTracks().forEach(track => track.stop());
    if (recorder === current) {
      clearTimeout(recordingTimer);
      recorder = null; recordingStream = null;
    }
    if (!valid()) return;
    const blob = new Blob(chunks, { type: mimeType });
    if (!blob.size || blob.size > 5 * 1024 * 1024) { voicePanel().innerHTML = errorBlock('녹음이 비어 있거나 너무 커요. 짧게 다시 녹음해 주세요.') + retry(); return; }
    voicePanel().innerHTML = loading('말씀을 글로 옮기고 있어요');
    try {
      const data = new FormData();
      const extension = mimeType.includes('mp4') ? 'm4a' : mimeType.includes('ogg') ? 'ogg' : 'webm';
      data.append('audio', blob, `reply.${extension}`);
      const result = await api(purpose === 'post' || purpose === 'memory' ? 'speech/transcribe/' : `posts/${postId}/replies/transcribe/`, { method: 'POST', data });
      if (!valid()) return;
      if (purpose === 'memory') {
        const text = (result.recognized || '').trim().slice(0, 1000), form = $('form[data-form="search"]'), field = $('#memory-question');
        if (!text) { voicePanel().innerHTML = memoryVoiceIdle('말씀을 알아듣지 못했어요. 다시 말씀해 주세요.'); return; }
        voicePanel().innerHTML = memoryVoiceIdle();
        // The question stays editable in the field; searching publishes nothing.
        if (form && field && !form.dataset.pending) { field.value = text; form.requestSubmit(); }
        return;
      }
      if (purpose === 'elder-reply') {
        const draft = await api(`posts/${postId}/replies/prepare/`, { method: 'POST', data: { recognized: result.recognized } });
        if (!valid()) return;
        voicePanel().innerHTML = `<div class="voice-review"><h4>이렇게 보낼게요</h4><p class="voice-draft">${e(draft.converted || draft.recognized)}</p><div class="button-row">${button('elder-reply-send', '가족에게 보내기', 'arrow', 'button primary', `data-id="${draft.id}" data-post="${postId}"`)}${button('elder-reply-record', '다시 말하기', 'mic', 'button quiet', `data-id="${postId}"`)}</div></div>`;
        return;
      }
      if (purpose === 'post') {
        voicePanel().innerHTML = `<label class="field"><span>말씀하신 내용 · 고친 뒤 글에 넣어 주세요</span><textarea data-post-voice maxlength="2000" rows="3">${e(result.recognized)}</textarea></label>${button('post-voice-insert', '글에 넣기', 'plus', 'button secondary')}`;
        return;
      }
      if (purpose) {
        const field = $(`[data-form="daily-${purpose}"] textarea`, modal);
        if (field) { field.value = result.recognized; field.focus(); }
        if (purpose === 'answer') dailyDraft.source = 'voice';
        captureDailyDraft();
        voicePanel().innerHTML = '<p class="help">글로 바꿨어요. 내용을 확인한 뒤 보내 주세요.</p>';
        return;
      }
      voicePanel().innerHTML = `<div class="voice-review"><h4>${icon('mic')}말씀하신 내용을 확인해 주세요</h4><form data-form="voice-prepare"><label class="field"><span>잘못 인식된 부분은 고칠 수 있어요.</span><textarea name="recognized" required maxlength="2000" rows="3">${e(result.recognized)}</textarea></label><p class="form-error" role="alert"></p><button type="submit" class="button secondary">다정한 답장으로 정리하기${icon('sparkle')}</button></form></div>`;
    } catch (error) { if (valid()) voicePanel().innerHTML = failureBlock(error, button(retryAction, error.status >= 500 ? '다시 시도하기' : '다시 녹음하기', 'mic', 'button secondary', purpose === 'elder-reply' ? `data-id="${postId}"` : ''), error.status >= 500 ? '잠시 후 다시 시도해 주세요' : '다시 말해 주세요'); }
  };
  current.start(1000);
  recordingTimer = setTimeout(() => {
    if (valid() && recorder === current) { stopRecording(); toast('2분이 되어 녹음을 마쳤어요.'); }
  }, 120000);
  if (purpose === 'memory') { voicePanel().innerHTML = `<div class="recording-status elder-recording"><span class="recording-dot"></span><strong>듣고 있어요</strong><span class="help">궁금한 것을 말씀하신 뒤 아래 버튼을 눌러 주세요.</span>${button('finish-record', '다 말했어요', 'stop', 'button primary')}${button('memory-voice-reset', '취소', '', 'button quiet')}</div>`; return; }
  if (purpose === 'elder-reply') { voicePanel().innerHTML = `<div class="recording-status elder-recording"><span class="recording-dot"></span><strong>듣고 있어요</strong><span class="help">다 말씀하시면 아래 버튼을 눌러 주세요.</span>${button('finish-record', '다 말했어요', 'stop', 'button primary')}${button('elder-reply-reset', '취소', '', 'button quiet', `data-id="${postId}"`)}</div>`; return; }
  voicePanel().innerHTML = `<div class="recording-status"><span class="recording-dot"></span><span>녹음 중이에요 · 최대 2분</span>${button('finish-record', '녹음 마치기', 'stop', 'button primary compact')}${button('cancel-record', '취소', '', 'button quiet compact')}</div>`;
}

const formHandlers = {
  async 'daily-answer'() {
    captureDailyDraft();
    const question = dailyQuestion, version = dailyRequest;
    const payload = questionPayload(question, dailyDraft);
    const updated = await api(`daily-questions/${question.id}/answer/`, { method: 'PUT', data: payload });
    if (version !== dailyRequest || !modal.open) return;
    dailyQuestion = updated;
    const mine = updated.answers.find(answer => answer.author_id === state.user.user_id);
    dailyDraft = { ...mine, editing: false, comment: dailyDraft.comment };
    dailyDrafts.set(dailyDraftKey(), { ...dailyDraft });
    renderDailyQuestion(); markDailySeen(updated);
    return { postingMessage: '답변을 남겼어요!' };
  },
  async 'daily-comment'(data) {
    if (!data.text.trim() || data.text.trim().length > 2000) throw new ApiError('댓글은 1~2,000자로 적어 주세요.');
    captureDailyDraft();
    const question = dailyQuestion, version = dailyRequest;
    const result = await api(`posts/${question.post_id}/comments/`, { method: 'POST', data: { text: data.text.trim() } });
    if (version !== dailyRequest || !modal.open) return;
    // Publication succeeded. Clear the draft even when the following read fails.
    dailyDraft.comment = '';
    dailyDrafts.set(dailyDraftKey(), { ...dailyDraft });
    try {
      const updated = await api(`daily-questions/${question.id}/`);
      if (version !== dailyRequest || !modal.open) return;
      dailyQuestion = updated; markDailySeen(updated);
    } catch {
      if (version !== dailyRequest || !modal.open) return;
      question.comments.push({ id: result.id, author_id: state.user.user_id, author_name: state.user.name, relationship: '나', text: data.text.trim() });
      toast('댓글은 등록됐어요. 최신 목록은 질문을 다시 열어 확인해 주세요.');
    }
    renderDailyQuestion();
    return { postingMessage: '댓글을 달았어요!' };
  },
  async login(data) {
    const result = await api('accounts/login/', { method: 'POST', data });
    setToken(result.token);
    await connectSession();
  },
  async register(data) {
    const selected = document.querySelector('[data-form="register"] [name="screen_mode"]')?.checked ? 'elder' : 'standard';
    const result = await api('accounts/register/', { method: 'POST', data });
    setToken(result.token);
    await connectSession();
    if (state.user) preferredModes.set(state.user.user_id, writeMode(localStorage, state.user.user_id, selected));
    applyScreenMode();
  },
  async 'create-room'(data) {
    const result = await api('families/create/', { method: 'POST', data });
    useRoom(result.room);
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
    if (room.members.some(member => member.id === state.user.user_id)) throw new ApiError('이미 참여한 가족방이에요. 가족방 목록에서 골라 들어가 주세요.');
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
    useRoom(result.room);
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
    clearPostDraft(draftScope());
    if (version === state.modalVersion) modal.close();
    if (currentRoute() === 'feed') await renderPage();
    else location.hash = '#/feed';
    return { postingMessage: '글 업로드가 완료됐어요.' };
  },
  async 'elder-reply'(data, form) {
    const id = Number(form.dataset.id), text = data.text.trim();
    if (!text || text.length > 2000) throw new ApiError('댓글은 1~2,000자로 적어 주세요.');
    await api(`posts/${id}/comments/`, { method: 'POST', data: { text } });
    clearCommentIfSent(draftScope(), id, text);
    closeElderReply(form.closest('.elder-reply')); toast('댓글을 달았어요!');
    await reloadInlineComments(id);
  },
  async comment(data, form) {
    const version = state.modalVersion;
    const postId = state.detail.id;
    await api(`posts/${postId}/comments/`, { method: 'POST', data });
    clearCommentIfSent(draftScope(), postId, data.text);
    if (version !== state.modalVersion) return;
    form.reset();
    // Publication already succeeded; a failed refresh must not invite sending twice.
    try {
      const result = await api(`posts/${postId}/`);
      if (version !== state.modalVersion) return;
      state.detail.comments = result.comments;
      renderComments();
      const post = state.posts.find(item => item.id === postId);
      if (post) { post.comment_count = result.comments.length; inlineComments.set(postId, result.comments); refreshPostComments(postId, result.comments); }
      const evidenceCount = $(`#search-result [data-post-id="${postId}"] .post-actions [data-action="open-post"] span`);
      if (evidenceCount) evidenceCount.textContent = result.comments.length;
    } catch { toast('댓글은 등록됐어요. 최신 댓글은 소식을 다시 열어 확인해 주세요.'); }
    if (version === state.modalVersion) return { postingMessage: '댓글을 달았어요!' };
  },
  async 'post-question'(data, form) {
    const version = state.modalVersion;
    const postId = state.detail.id, past = pastQuestions(draftScope(), postId);
    const result = await api(`posts/${postId}/questions/`, { method: 'POST', data: { question: data.question, prior_dialogue: [...past, ...state.dialogue].slice(-10).map(turn => ({ ...turn, text: turn.text.slice(0, 1000) })) } });
    if (version !== state.modalVersion) return;
    state.dialogue.push({ role: 'user', text: data.question }, { role: 'assistant', text: result.text });
    // Remembered after rendering so this answer shows below the toggle, not inside it, until the next opening.
    $('#question-history').innerHTML = questionHistoryMarkup();
    rememberQuestion(draftScope(), postId, data.question, result.text);
    form.reset();
  },
  async search(data) {
    const version = state.pageVersion;
    const session = state.session;
    const room = state.room.id;
    const current = () => version === state.pageVersion && session === state.session && room === state.room?.id;
    $('#search-result').innerHTML = loading('가족의 추억을 찾고 있어요');
    try {
      const result = await api('searching/history/', { method: 'POST', data, room });
      if (!current()) return;
      const evidence = await memoryEvidence(result, id => api(`posts/${id}/`, { room }));
      if (!current()) return;
      queueMicrotask(() => { if (tabTour === 'memory-listen') tourStep('memory-listen'); });
      $('#search-result').innerHTML = memoryResultMarkup(result.text, evidence);
      rememberMemorySearch(draftScope(), data.question, result.text, evidence.posts, evidence.unavailable);
      $('#memory-past').innerHTML = pastMemoriesMarkup(memorySearches(draftScope()), e);
      hydrateImages($('#search-result'));
    } catch (error) { if (current()) $('#search-result').innerHTML = ''; throw error; }
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
  async voice(data) {
    const result = await api('accounts/me/', { method: 'PATCH', data: { tts_voice: data.tts_voice } });
    state.user = { ...state.user, ...result };
    toast('목소리를 저장했어요.');
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
    $('#voice-panel').innerHTML = `<div class="voice-review"><span class="tag">보내기 전 마지막 확인</span><h4>이렇게 마음을 전할까요?</h4><p class="voice-draft">${e(draft.converted)}</p><p class="help">아래 버튼을 누르면 이 글이 가족 댓글로 전송돼요.</p><div class="button-row">${button('send-voice', '이대로 답장 보내기', 'arrow', 'button primary', `data-id="${draft.id}"`)}${button('reply-rerecord', '다시 말하기', 'mic', 'button quiet')}</div></div>`;
  },
};

document.addEventListener('invalid', event => {
  const input = event.target;
  if (input.closest('form[data-form]')) showFieldError(input.form, { field: input.name, message:
    input.validity.valueMissing ? '이 항목을 입력해 주세요.' : input.validationMessage });
}, true);

document.addEventListener('submit', async event => {
  const form = event.target.closest('form[data-form]');
  if (!form) return;
  event.preventDefault();
  if (form.dataset.pending) return;
  const handler = formHandlers[form.dataset.form];
  if (!handler) return;
  form.dataset.pending = 'true';
  let data = Object.fromEntries(new FormData(form));
  if (form.dataset.form === 'register') {
    try { data = registrationPayload(data); }
    catch (error) {
      showFieldError(form, error);
      delete form.dataset.pending;
      return;
    }
  }
  try { await busy(event.submitter || $('[type="submit"]', form), () => handler(data, form), $('.form-error', form)); }
  finally { delete form.dataset.pending; }
});

document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]');
  if (!target || target.disabled) return;
  const action = target.dataset.action;
  // Elderly tab tour: pressing the pointed-at button moves on to the next step.
  if (tabTour) {
    if (action === 'tab-hint-close') { endTabTour(); return; }
    if (action === 'digest-audio' && tabTour === 'day-listen') { tabTour = 'day-listening'; pointAt(null); whenAudioEnds(() => { if (tabTour === 'day-listening') tourStep('day-previous'); }); }
    else if (action === 'elder-day-step' && (tabTour === 'day-previous' || tabTour === 'day-listening')) endTabTour();
    else if (action === 'memory-example' && tabTour === 'memory-example') { tabTour = 'memory-listen'; $('#page .tab-hint p').textContent = TAB_TOUR['memory-listen'][0]; pointAt(null); }
    else if (action === 'memory-audio' && tabTour === 'memory-listen') { tabTour = 'memory-listening'; pointAt(null); whenAudioEnds(() => { if (tabTour === 'memory-listening') tourStep('memory-voice'); }); }
    else if (action === 'memory-voice' && (tabTour === 'memory-voice' || tabTour === 'memory-listening')) endTabTour();
  }
  if (action === 'screen-standard' || action === 'screen-elder') {
    preferredModes.set(state.user.user_id, writeMode(localStorage, state.user.user_id, action === 'screen-elder' ? 'elder' : 'standard'));
    renderShell(); return renderPage();
  }
  if (action === 'switch-account') { resetSession(); return renderAuth(); }
  if (action === 'expand-post') {
    const id = Number(target.dataset.id); expandedPosts.add(id);
    const caption = target.closest('.post-card').querySelector('.post-caption'); caption.classList.remove('caption-clamped'); target.remove(); return;
  }
  if (action === 'retry-comments') {
    const id = Number(target.dataset.id), key = `${state.session}:${state.room.id}:${id}`;
    if (!pendingComments.has(key)) { pendingComments.add(key); commentQueue.push({ id, key, session: state.session, room: state.room.id }); drainInlineComments(); }
    return;
  }
  if (action === 'elder-comment') return toggleElderReply(Number(target.dataset.id));
  // One help button: it starts the guide for the tab it is pressed on.
  if (action === 'elder-help') {
    const route = currentRoute();
    if (route === 'digest' && $('.elder-day-title')) return tourStep($('[data-action="digest-audio"]') ? 'day-listen' : 'day-previous');
    if (route === 'search' && $('[data-action="memory-example"]')) return tourStep('memory-example');
    return openPractice(true);
  }
  if (action === 'tab-hint-close') { target.closest('.tab-hint')?.remove(); return; }
  if (action === 'elder-day-step') {
    const next = new Date(`${selectedDigestDate}T12:00:00Z`); next.setUTCDate(next.getUTCDate() + Number(target.dataset.step));
    const date = next.toISOString().slice(0, 10); if (date > today()) return;
    selectedDigestDate = date; return renderPage();
  }
  if (action === 'memory-voice') {
    const slot = target.closest('.memory-voice'); if (!slot) return;
    stopAudio(); stopRecording(true);
    return busy(target, () => startRecording({ purpose: 'memory', target: slot }), $('form[data-form="search"] .form-error'));
  }
  if (action === 'memory-voice-reset') { stopRecording(true); elderRecording = false; const slot = target.closest('.memory-voice'); if (slot) slot.innerHTML = memoryVoiceIdle(); return; }
  if (action === 'memory-example') {
    const form = $('form[data-form="search"]'), field = $('#memory-question');
    if (!form || !field || form.dataset.pending) return;
    field.value = target.dataset.question; form.requestSubmit(); return;
  }
  if (action === 'memory-audio') {
    const answer = target.closest('.search-answer'), text = answer?.querySelector('.answer-text')?.textContent, version = state.pageVersion;
    return busy(target, () => playSpeech(text, $('[data-action="stop-audio"]', answer), () => version === state.pageVersion));
  }
  if (action === 'post-ask') { stopAudio(); assistant.targetId = Number(target.dataset.id); assistant.open(); return; }
  if (action === 'memory-past') {
    // A saved search shows its stored answer and posts again; nothing is sent to the AI.
    const item = memorySearches(draftScope())[Number(target.dataset.index)];
    if (!item) return;
    const field = $('#memory-question'); if (field) field.value = item.question;
    target.closest('details')?.removeAttribute('open');
    $('#search-result').innerHTML = memoryResultMarkup(item.text, { posts: item.posts, unavailable: item.unavailable });
    hydrateImages($('#search-result'));
    return;
  }
  if (action === 'elder-reply-close') return closeElderReply(target.closest('.elder-reply'));
  if (action === 'elder-reply-reset') { stopRecording(true); elderRecording = false; const slot = target.closest('.elder-reply-voice'); if (slot) slot.innerHTML = elderVoiceIdle(Number(target.dataset.id)); return; }
  if (action === 'elder-reply-record') {
    const panel = target.closest('.elder-reply'), slot = panel?.querySelector('.elder-reply-voice'); if (!slot) return;
    stopAudio(); stopRecording(true);
    return busy(target, () => startRecording({ postId: Number(target.dataset.id), purpose: 'elder-reply', target: slot }), panel.querySelector('.form-error'));
  }
  if (action === 'elder-reply-send') {
    const id = Number(target.dataset.post), panel = target.closest('.elder-reply');
    return busy(target, async () => {
      await api(`replies/${Number(target.dataset.id)}/send/`, { method: 'POST' });
      closeElderReply(panel); toast('댓글을 달았어요!');
      await reloadInlineComments(id);
    }, panel?.querySelector('.form-error'));
  }
  if (action === 'feed-comments' || action === 'feed-voice') {
    await openPost(Number(target.dataset.id));
    if (!state.detail || state.detail.id !== Number(target.dataset.id)) return;
    if (action !== 'elder-comment') { modal.classList.add('comments-only'); $('#modal-title').textContent = '댓글'; }
    if (action === 'feed-voice') { $('#voice-panel').innerHTML = `<p class="help">버튼을 누르고 말씀해 주세요.</p>${button('record', '말하기 시작', 'mic', 'button primary compact')}`; return; }
    const field = $('#comment-text', modal); field?.scrollIntoView({ block: 'nearest' }); field?.focus({ preventScroll: true }); return;
  }
  if (action === 'feed-stop-listen') { stopAudio(); target.dataset.action='feed-listen'; target.innerHTML=icon('volume')+feedListenLabel();target.setAttribute('aria-label','소식 듣기'); return; }
  if (action === 'feed-listen') return listenToPost(Number(target.dataset.id), target);
  if (action === 'digest-story') return showDigestStory();
  if (action === 'day-prev' || action === 'day-next') { digestMonth.setUTCMonth(digestMonth.getUTCMonth() + (action === 'day-next' ? 1 : -1)); renderMonth(); return; }
  if (action === 'auth-login') return renderAuth(false);
  if (action === 'auth-register') return renderAuth(true);
  if (action === 'close-modal') return modal.close();
  if (action === 'daily-open') return openDailyQuestion();
  if (action === 'daily-today' || action === 'daily-detail') { stopRecording(true); return loadDailyQuestion(target.dataset.id); }
  if (action === 'daily-history') { stopRecording(true); return loadDailyHistory(); }
  if (action === 'daily-more') return busy(target, () => loadDailyHistory(target.dataset.before));
  if (action === 'daily-edit' && dailyDraft) {
    captureDailyDraft(); dailyDraft.editing = true; renderDailyQuestion();
    captureDailyDraft(); $('[data-form="daily-answer"] input, [data-form="daily-answer"] select, [data-form="daily-answer"] textarea', modal)?.focus();
    return;
  }
  if (action === 'daily-record-answer' || action === 'daily-record-comment') {
    if (!dailyQuestion) return;
    return busy(target, () => startRecording({ postId: dailyQuestion.post_id, purpose: action.endsWith('answer') ? 'answer' : 'comment' }));
  }
  if (action === 'text-size') { writeMode(localStorage, state.user.user_id, elder ? 'standard' : 'elder'); renderShell(); return renderPage(); }
  if (action === 'undo-tree' && state.lookup) { state.lookup.draft.undo(); renderJoinPreview(); return; }
  if (action === 'compose') return openComposer();
  if (action === 'open-post' || action === 'retry-post' || action === 'post-summary') return openPost(Number(target.dataset.id), action === 'post-summary');
  if (action === 'select-photo') return showPhoto(Number(target.dataset.index));
  if (action === 'remove-photo') { state.files.splice(Number(target.dataset.index), 1); return renderPreviews(); }
  if (action === 'refresh-page' || action === 'refresh-feed') return renderPage();
  if (action === 'open-room') {
    const id = Number(target.dataset.id);
    if (id === state.room?.id) { location.hash = '#/feed'; return; }
    return busy(target, () => openRoom(id));
  }
  if (action === 'stop-audio') return stopAudio();
  if (action === 'summary-audio') return listenToSummary();
  if (action === 'record-post') return busy(target, () => startRecording({ purpose: 'post' }));
  if (action === 'post-voice-insert') {
    const field = $('#post-caption'), transcript = $('[data-post-voice]')?.value.trim() || '';
    if (!transcript) return toast('넣을 내용을 입력해 주세요.');
    const text = [field.value.trimEnd(), transcript].filter(Boolean).join('\n');
    if (text.length > 2000) return toast('소식은 모두 2,000자까지 쓸 수 있어요. 내용을 줄여 주세요.');
    field.value = text; field.dispatchEvent(new Event('input', { bubbles: true }));
    $('#voice-panel').innerHTML = '<p class="help">글에 넣었어요. 내용을 확인한 뒤 가족에게 전해 주세요.</p>';
    return;
  }
  if (action === 'reply-rerecord') { stopRecording(true); $('#voice-panel').innerHTML = `<p class="help">버튼을 누르고 말씀해 주세요.</p>${button('record', '말하기 시작', 'mic', 'button primary compact')}`; return; }
  if (action === 'cancel-record') { stopRecording(true); $('#voice-panel').innerHTML = ''; return; }
  if (action === 'finish-record') { stopRecording(); return; }
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
      if (state.user) clearAccountDrafts(state.user.user_id);
      resetSession(); renderAuth();
    }
    if (action === 'copy-code') {
      if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(state.room.invite_code); toast('초대코드를 복사했어요.'); }
      else toast(`초대코드: ${state.room.invite_code} · 코드를 직접 복사해 주세요.`);
    }
    if (action === 'summary') await loadSummary();
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
      try {
        const post = await api(`posts/${postId}/`);
        if (version !== state.modalVersion) return;
        state.detail.comments = post.comments;
        renderComments();
        const feedPost = state.posts.find(item => item.id === postId);
        if (feedPost) { feedPost.comment_count = post.comments.length; inlineComments.set(postId, post.comments); refreshPostComments(postId, post.comments); }
      } catch { toast('댓글은 등록됐어요. 최신 댓글은 소식을 다시 열어 확인해 주세요.'); }
      if (version === state.modalVersion) return { postingMessage: '댓글을 달았어요!' };
    }
  });
});
document.addEventListener('input', event => {
  if (event.target.closest('[data-form^="daily-"]')) captureDailyDraft();
  if (event.target.name === 'invite_code') {
    const input = event.target, start = input.selectionStart, end = input.selectionEnd;
    input.value = input.value.toUpperCase(); input.setSelectionRange(start, end);
  }
  if (event.target.matches('input')) {
    event.target.removeAttribute('aria-invalid'); event.target.removeAttribute('aria-describedby');
    event.target.parentElement.querySelector('.field-error')?.remove();
  }
  if (event.target.closest('[data-form="lookup-room"]')) { state.lookup = null; $('#join-panel').innerHTML = ''; }
});
document.addEventListener('change', event => {
  if (event.target.matches('[data-form="daily-answer"] input[type="radio"]')) {
    const form = event.target.form;
    const other = form.elements.namedItem('other_text');
    if (other) {
      other.hidden = other.disabled = event.target.value !== '기타';
      other.required = !other.hidden;
      if (!other.hidden) other.focus();
    }
    form.querySelectorAll('.daily-option').forEach(row => row.classList.toggle('selected', row.querySelector('input[type="radio"]').checked));
  }
  if (event.target.closest('[data-form^="daily-"]')) captureDailyDraft();
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
function openBotMenu() {
  assistant.sync();
  const id = assistant.targetId, roomId = state.room?.id, session = state.session;
  const menu = document.createElement('dialog'); menu.className = 'bot-menu-dialog';
  menu.setAttribute('aria-label', '토닥 도우미 메뉴');
  // The elderly screen asks about a post from the card, right after listening to it.
  const rows = [...(elder ? [] : [['ask','comment','이 소식 물어보기',true]]),['listen','volume',document.querySelector(`#feed-list [data-action="feed-stop-listen"][data-id="${id}"]`) ? '듣기 중지' : '음성으로 듣기',true],['summary','sparkle','AI 요약 보기',true],['memory','search','가족 추억 찾기',false],['day','calendar','오늘 가족의 하루',false],['help','book','도움말',false]];
  menu.innerHTML = `<header><h2>무엇을 도와드릴까요?</h2><button type="button" class="icon-button" data-bot="close" aria-label="도우미 메뉴 닫기">${icon('close')}</button></header>${rows.map(([action,symbol,label,needsPost])=>`<button type="button" data-bot="${action}" ${needsPost&&id===null?'disabled':''}>${icon(symbol)}<span>${label}</span>${icon('chevron')}</button>`).join('')}`;
  document.body.append(menu); menu.showModal();
  menu.addEventListener('close',()=>menu.remove(),{once:true});
  menu.onclick=async event=>{
    const button=event.target.closest('[data-bot]');if(!button||button.disabled)return;
    const action=button.dataset.bot;menu.close();
    if(session!==state.session||roomId!==state.room?.id)return;
    if(action==='help')return openPractice(true);
    if(action==='memory'){location.hash='#/search';return;}
    if(action==='day'){location.hash='#/digest';return;}
    if(action==='ask'){assistant.targetId=id;assistant.open();return;}
    if(action==='listen' && document.querySelector(`#feed-list [data-action="feed-stop-listen"][data-id="${id}"]`))return stopAudio();
    if(action==='listen')return listenToPost(id,document.querySelector(`#feed-list [data-action="feed-listen"][data-id="${id}"]`)||button);
    if(action==='summary')return openPost(id,true);
  };
}
document.querySelector('#assistant-root').addEventListener('click',event=>{
  if(!event.target.closest('.assistant-launcher') || (event.detail && performance.now() < (assistant.suppressClickUntil||0)))return;
  event.preventDefault();event.stopImmediatePropagation();openBotMenu();
},true);

window.addEventListener('pagehide', () => { stopRecording(true); stopAudio(); clearImages(); });
document.documentElement.classList.toggle('large-text', localStorage.getItem('talkdock.web.largeText') === 'true');
if (hasToken()) connectSession();
else renderAuth();
document.addEventListener('click', event => { const target = event.target.closest('[data-action="retry-enter"]'); if (target) busy(target, connectSession); });
