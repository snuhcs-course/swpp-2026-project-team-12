import { LAUNCHER_SIZE, centeredPost, fitPanel, launcherPlacement, launcherPosition, restoreLauncher, PostConversations } from './assistant-state.js';
import { icon } from './icons.js';

const LAYOUT_KEY = 'talkdock.web.assistant.layout.v1';
const escape = value => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const clamp = (n, min, max) => Math.min(max, Math.max(min, n));
const character = '<img src="/web/assets/assistant_character.png" alt="" draggable="false">';

export class FloatingAssistant {
  constructor({ root, context, ask }) {
    this.root = root; this.context = context; this.ask = ask;
    root.style.setProperty('--assistant-launcher-size', `${LAUNCHER_SIZE}px`);
    this.conversations = new PostConversations();
    this.targetId = null; this.opened = false; this.frame = null; this.gesture = null;
    try { this.layout = JSON.parse(localStorage.getItem(LAYOUT_KEY)) || {}; } catch { this.layout = {}; }
    if (!this.layout || typeof this.layout !== 'object' || Array.isArray(this.layout)) this.layout = {};
    this.placement = restoreLauncher(this.layout.button);
    this.panelRect = this.layout.panel && typeof this.layout.panel === 'object' ? this.layout.panel : null;
    root.innerHTML = `<div class="assistant-shade" hidden aria-hidden="true"></div>
      <button type="button" class="assistant-launcher" aria-label="토닥 도우미 열기" aria-expanded="false" aria-controls="assistant-panel" title="토닥 도우미 · 드래그로 이동" hidden><span class="assistant-launcher-portrait" aria-hidden="true">${character}</span><span class="assistant-launcher-mark" aria-hidden="true">${icon('sparkle')}</span></button>
      <section id="assistant-panel" class="assistant-panel" role="region" aria-labelledby="assistant-title" hidden>
        <header class="assistant-header"><span class="assistant-avatar" aria-hidden="true">${character}</span><h2 id="assistant-title"><button type="button" class="assistant-grip" title="드래그하거나 방향키로 대화창 이동">이 글에 대해 궁금하세요?</button></h2><div class="assistant-controls"><button type="button" class="assistant-close icon-button" aria-label="도우미 닫기" title="닫기">${icon('close')}</button></div></header>
        <div class="assistant-history" role="log" aria-label="현재 게시글에 대한 대화" aria-live="polite" aria-relevant="additions text"></div>
        <form class="assistant-form"><label class="sr-only" for="assistant-question">이 글에 대해 질문하기</label><div class="assistant-input-row"><textarea id="assistant-question" rows="2" maxlength="1000" placeholder="궁금한 점을 편하게 물어보세요." enterkeyhint="send"></textarea><button type="submit" class="assistant-send" aria-label="질문 보내기">${icon('arrow')}</button></div><p class="assistant-error" role="alert" hidden></p><p class="assistant-hint">밝게 표시된 소식에 대해 함께 이야기해요.</p></form>
        <div class="assistant-resize-handles">${['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'].map(edge => `<button type="button" class="assistant-resize assistant-resize-${edge}" data-edge="${edge}" aria-label="대화창 ${({n:'위',s:'아래',e:'오른쪽',w:'왼쪽',ne:'오른쪽 위',nw:'왼쪽 위',se:'오른쪽 아래',sw:'왼쪽 아래'})[edge]} 크기 조절. 방향키를 사용하세요."></button>`).join('')}</div>
      </section><span class="sr-only assistant-status" role="status"></span>`;
    const find = selector => root.querySelector(selector);
    this.launcher = find('.assistant-launcher'); this.panel = find('.assistant-panel'); this.shade = find('.assistant-shade');
    this.history = find('.assistant-history'); this.input = find('textarea'); this.sendButton = find('.assistant-send');
    this.error = find('.assistant-error'); this.status = find('.assistant-status');
    this.launcher.addEventListener('click', event => {
      if (event.detail && performance.now() < (this.suppressClickUntil || 0)) return;
      this.sync();
      if (this.launcher.hidden) return;
      if (this.opened) this.close(); else this.open();
    });
    find('.assistant-close').addEventListener('click', () => this.close());
    this.input.addEventListener('input', () => {
      if (this.targetId !== null) { this.conversations.entry(this.targetId).draft = this.input.value; this.updateSendButton(); }
    });
    this.input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); find('form').requestSubmit(); }
    });
    find('form').addEventListener('submit', event => {
      event.preventDefault();
      const displayed = this.targetId;
      this.sync(); // A scroll can precede the next animation frame; never submit the old draft to a new post.
      if (displayed === null || displayed !== this.targetId) return;
      const id = this.targetId, { roomId } = this.context();
      this.conversations.send(id, (question, dialogue) => this.ask({ id, roomId, question, dialogue }), () => {
        if (this.targetId === id) this.renderConversation();
      });
    });
    this.launcher.addEventListener('pointerdown', event => this.startGesture(event, 'launcher'));
    find('.assistant-grip').addEventListener('pointerdown', event => this.startGesture(event, 'move'));
    find('.assistant-grip').addEventListener('keydown', event => this.keyboardMove(event, false));
    this.launcher.addEventListener('keydown', event => this.keyboardMove(event, true));
    root.querySelectorAll('[data-edge]').forEach(handle => {
      handle.addEventListener('pointerdown', event => this.startGesture(event, 'resize', handle.dataset.edge));
      handle.addEventListener('keydown', event => {
        const delta = this.keyDelta(event); if (!delta || this.mobile()) return;
        this.resize(this.panelRect, delta.x, delta.y, handle.dataset.edge); this.save();
      });
    });
    root.addEventListener('pointermove', event => this.moveGesture(event));
    root.addEventListener('pointerup', event => this.endGesture(event));
    root.addEventListener('pointercancel', event => this.endGesture(event, true));
    root.addEventListener('lostpointercapture', event => { if (this.gesture) this.endGesture(event, true); });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && this.opened && !document.querySelector('dialog[open]')) { event.preventDefault(); this.close(); }
    });
    document.addEventListener('scroll', () => this.refresh(), { capture: true, passive: true });
    window.addEventListener('resize', () => { this.positionLauncher(); if (this.opened) this.positionPanel(); this.refresh(); });
    window.visualViewport?.addEventListener('resize', () => { this.positionLauncher(); if (this.opened) this.positionPanel(); this.refresh(); });
    window.visualViewport?.addEventListener('scroll', () => { this.positionLauncher(); if (this.opened) this.positionPanel(); this.refresh(); });
    new ResizeObserver(() => this.refresh()).observe(document.querySelector('#app'));
    new MutationObserver(() => this.refresh()).observe(document.querySelector('#app'), { childList: true, subtree: true });
    document.querySelector('#app').addEventListener('load', () => this.refresh(), true);
    this.refresh();
  }
  viewport() {
    const view = window.visualViewport;
    return { left: view?.offsetLeft || 0, top: view?.offsetTop || 0, width: view?.width || innerWidth, height: view?.height || innerHeight };
  }
  mobile() { return this.viewport().width <= 640; }
  save() {
    // Store geometry only; drafts, questions and answers remain in this tab's memory.
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify({ button: this.placement, panel: this.panelRect })); } catch { /* Private browsing may block storage. */ }
  }
  refresh() {
    if (this.frame !== null) return;
    this.frame = requestAnimationFrame(() => { this.frame = null; this.sync(); });
  }
  reset() {
    this.close(false); this.conversations.reset(); this.targetId = null;
    this.history.replaceChildren(); this.input.value = ''; this.error.textContent = ''; this.launcher.hidden = true;
  }
  sync() {
    const context = this.context();
    if (context.scope !== this.conversations.scope) { this.reset(); this.conversations.setScope(context.scope); }
    const available = Boolean(context.enabled && context.scope);
    this.launcher.hidden = !available || this.opened;
    if (!available) { this.close(false); return; }
    this.positionLauncher();
    const view = this.viewport();
    const header = document.querySelector('.topbar')?.getBoundingClientRect();
    const viewport = { left: view.left, right: view.left + view.width, top: Math.max(view.top, header?.bottom || 0), bottom: view.top + view.height };
    const nodes = [...document.querySelectorAll('#feed-list .post-card[data-post-id]')];
    const cards = nodes.map(node => ({ id: Number(node.dataset.postId), ...node.getBoundingClientRect().toJSON() }));
    const id = centeredPost(cards, viewport, this.targetId);
    if (id !== this.targetId) {
      this.rememberScroll(); this.targetId = id;
      this.renderConversation();
      if (this.opened) this.status.textContent = id === null ? '화면 가운데에 소식을 가져와 주세요.' : '화면 중앙 소식의 대화로 전환했어요.';
    }
    if (this.opened && id !== null) {
      const rect = cards.find(card => card.id === id);
      const left = Math.max(rect.left, viewport.left), top = Math.max(rect.top, viewport.top);
      Object.assign(this.shade.style, { left: `${left}px`, top: `${top}px`, width: `${Math.min(rect.right, viewport.right) - left}px`, height: `${Math.min(rect.bottom, viewport.bottom) - top}px` });
      this.shade.hidden = false;
    } else this.shade.hidden = true;
  }
  open() {
    this.opened = true; this.panel.hidden = false;
    this.launcher.setAttribute('aria-expanded', 'true'); this.launcher.setAttribute('aria-label', '토닥 도우미 접기');
    if (!this.panelRect) {
      const button = this.launcher.getBoundingClientRect();
      const view = this.viewport();
      this.panelRect = { x: button.left + button.width / 2 >= view.left + view.width / 2 ? button.left - 416 : button.right + 16, y: button.bottom - 540, width: 400, height: 540 };
    }
    this.positionPanel(); this.renderConversation(); this.sync();
    this.panel.querySelector('.assistant-grip').focus({ preventScroll: true });
  }
  close(focus = true) {
    if (this.opened) this.rememberScroll();
    const inside = this.panel.contains(document.activeElement);
    this.opened = false; this.panel.hidden = true; this.shade.hidden = true;
    const { enabled, scope } = this.context();
    this.launcher.hidden = !(enabled && scope);
    this.launcher.setAttribute('aria-expanded', 'false'); this.launcher.setAttribute('aria-label', '토닥 도우미 열기');
    this.positionLauncher();
    if (focus && inside && !this.launcher.hidden) this.launcher.focus({ preventScroll: true });
  }
  rememberScroll() { if (this.opened && this.targetId !== null) this.conversations.entry(this.targetId).scrollTop = this.history.scrollTop; }
  renderConversation() {
    const entry = this.targetId === null ? null : this.conversations.entry(this.targetId);
    const scroll = entry?.scrollTop;
    this.history.innerHTML = !entry ? `<div class="assistant-welcome">${character}<h3>어떤 소식이 궁금하세요?</h3><p>궁금한 소식을 화면 가운데로<br>가져와 주세요.</p></div>` :
      (entry.turns.length || entry.pending ? entry.turns.map(turn => `<div class="assistant-turn ${turn.role}"><span>${turn.role === 'user' ? '나' : '토닥'}</span><p>${escape(turn.text)}</p></div>`).join('') : `<div class="assistant-welcome">${character}<h3>이 소식, 함께 읽어볼까요?</h3><p>궁금한 점을 편하게 물어보세요.<br>스크롤하면 새 소식의 대화로 바뀌어요.</p></div>`);
    if (entry?.pending) this.history.insertAdjacentHTML('beforeend', `<div class="assistant-turn user"><span>나</span><p>${escape(entry.question)}</p></div><div class="assistant-thinking" role="status"><span></span><span></span><span></span>소식을 살펴보고 있어요.</div>`);
    const draft = entry?.draft || '';
    if (this.input.value !== draft) this.input.value = draft;
    this.input.disabled = !entry;
    this.error.textContent = entry?.error || ''; this.error.hidden = !entry?.error;
    this.updateSendButton();
    // Rendering while closed cannot measure scroll height; restore again when opened.
    if (this.opened) this.history.scrollTop = scroll ?? this.history.scrollHeight;
  }
  updateSendButton() {
    const entry = this.targetId === null ? null : this.conversations.entry(this.targetId);
    this.sendButton.disabled = !entry || entry.pending || !entry.draft.trim();
    this.sendButton.setAttribute('aria-busy', String(Boolean(entry?.pending)));
  }
  positionLauncher() {
    if (this.gesture?.kind === 'launcher' && this.gesture.moved) return;
    const point = launcherPosition(this.placement, this.viewport());
    Object.assign(this.launcher.style, { left: `${point.x}px`, top: `${point.y}px` });
  }
  positionPanel() {
    const view = this.viewport();
    let rect = fitPanel(this.panelRect || {}, view);
    if (this.mobile()) {
      const height = Math.min(rect.height, 540, view.height * .65, Math.max(1, view.height - 112));
      rect = { x: view.left + 12, y: view.top + Math.max(12, view.height - height - 96), width: Math.max(1, view.width - 24), height };
    } else this.panelRect = rect;
    Object.assign(this.panel.style, { left: `${rect.x}px`, top: `${rect.y}px`, width: `${rect.width}px`, height: `${rect.height}px` });
  }
  keyDelta(event) {
    const step = event.shiftKey ? 40 : 16;
    const delta = { ArrowLeft: { x: -step, y: 0 }, ArrowRight: { x: step, y: 0 }, ArrowUp: { x: 0, y: -step }, ArrowDown: { x: 0, y: step } }[event.key];
    if (delta) event.preventDefault();
    return delta;
  }
  keyboardMove(event, launcher) {
    const delta = this.keyDelta(event); if (!delta) return;
    if (launcher) {
      const view = this.viewport(), point = launcherPosition(this.placement, view);
      this.close(false);
      this.placement = launcherPlacement({ x: point.x + delta.x, y: point.y + delta.y }, view);
      this.positionLauncher();
    } else if (!this.mobile()) {
      this.panelRect = fitPanel({ ...this.panelRect, x: this.panelRect.x + delta.x, y: this.panelRect.y + delta.y }, this.viewport());
      this.positionPanel();
    }
    this.save();
  }
  startGesture(event, kind, edge) {
    if (!event.isPrimary || event.button !== 0 || (kind !== 'launcher' && this.mobile())) return;
    const capture = event.currentTarget;
    this.gesture = { pointerId: event.pointerId, capture, kind, edge, x: event.clientX, y: event.clientY, moved: false,
      rect: { ...(this.panelRect || {}) }, placement: { ...this.placement }, button: this.launcher.getBoundingClientRect() };
    capture.setPointerCapture(event.pointerId);
    if (kind !== 'launcher') event.preventDefault();
  }
  moveGesture(event) {
    const g = this.gesture; if (!g || g.pointerId !== event.pointerId) return;
    const dx = event.clientX - g.x, dy = event.clientY - g.y;
    if (!g.moved && Math.hypot(dx, dy) < 6) return;
    if (!g.moved && g.kind === 'launcher') this.close(false);
    g.moved = true; event.preventDefault();
    if (g.kind === 'launcher') {
      const view = this.viewport();
      const point = launcherPosition(launcherPlacement({ x: g.button.left + dx, y: g.button.top + dy }, view), view);
      Object.assign(this.launcher.style, { left: `${point.x}px`, top: `${point.y}px` });
    } else if (g.kind === 'move') {
      this.panelRect = fitPanel({ ...g.rect, x: g.rect.x + dx, y: g.rect.y + dy }, this.viewport()); this.positionPanel();
    } else this.resize(g.rect, dx, dy, g.edge);
  }
  resize(rect, dx, dy, edge) {
    const view = this.viewport(), minWidth = Math.min(320, view.width - 24), minHeight = Math.min(300, view.height - 24);
    let left = rect.x, right = rect.x + rect.width, top = rect.y, bottom = rect.y + rect.height;
    if (edge.includes('w')) left = clamp(left + dx, view.left + 12, right - minWidth);
    if (edge.includes('e')) right = clamp(right + dx, left + minWidth, view.left + view.width - 12);
    if (edge.includes('n')) top = clamp(top + dy, view.top + 12, bottom - minHeight);
    if (edge.includes('s')) bottom = clamp(bottom + dy, top + minHeight, view.top + view.height - 12);
    this.panelRect = fitPanel({ x: left, y: top, width: right - left, height: bottom - top }, view); this.positionPanel();
  }
  endGesture(event, cancelled = false) {
    const g = this.gesture; if (!g || g.pointerId !== event.pointerId) return;
    this.gesture = null;
    if (g.capture.hasPointerCapture(event.pointerId)) g.capture.releasePointerCapture(event.pointerId);
    if (g.moved) {
      this.suppressClickUntil = performance.now() + 500;
      if (cancelled) { this.placement = g.placement; this.panelRect = Object.keys(g.rect).length ? g.rect : null; }
      else if (g.kind === 'launcher') {
        const view = this.viewport(), rect = this.launcher.getBoundingClientRect();
        this.placement = launcherPlacement({ x: rect.left, y: rect.top }, view);
      }
      this.positionLauncher(); if (this.opened) this.positionPanel(); this.save();
    }
  }
}
