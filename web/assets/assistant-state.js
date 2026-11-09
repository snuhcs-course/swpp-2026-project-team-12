// Browser-independent state: conversations never leave memory or cross accounts/rooms.
export const LAUNCHER_SIZE = 96;
export function centeredPost(cards, viewport, previous = null) {
  const middle = (viewport.top + viewport.bottom) / 2;
  let selected = null, distance = Infinity;
  for (const card of cards) {
    const top = Math.max(card.top, viewport.top), bottom = Math.min(card.bottom, viewport.bottom);
    if (bottom <= top || card.right <= viewport.left || card.left >= viewport.right) continue;
    const next = Math.abs((top + bottom) / 2 - middle);
    if (next < distance || (next === distance && card.id === previous)) {
      selected = card.id; distance = next;
    }
  }
  return selected;
}

export function fitPanel(rect, viewport) {
  const margin = 12;
  const maxWidth = Math.max(1, viewport.width - margin * 2);
  const maxHeight = Math.max(1, viewport.height - margin * 2);
  const finite = (value, fallback) => Number.isFinite(value) ? value : fallback;
  const width = Math.min(maxWidth, Math.max(Math.min(320, maxWidth), finite(rect.width, 400)));
  const height = Math.min(maxHeight, Math.max(Math.min(300, maxHeight), finite(rect.height, 540)));
  return {
    x: Math.min(viewport.left + viewport.width - width - margin, Math.max(viewport.left + margin, finite(rect.x, viewport.left + maxWidth - width))),
    y: Math.min(viewport.top + viewport.height - height - margin, Math.max(viewport.top + margin, finite(rect.y, viewport.top + 24))),
    width, height,
  };
}

export function restoreLauncher(saved) {
  const ratio = (value, fallback) => Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : fallback;
  return {
    xRatio: ratio(saved?.xRatio, saved?.side === 'left' ? 0 : 1),
    yRatio: ratio(saved?.yRatio, ratio(saved?.ratio, 1)),
  };
}

function launcherBounds(viewport) {
  const xMargin = Math.min(20, Math.max(0, (viewport.width - LAUNCHER_SIZE) / 2));
  const yMargin = Math.min(20, Math.max(0, (viewport.height - LAUNCHER_SIZE) / 2));
  return { x: viewport.left + xMargin, y: viewport.top + yMargin,
    width: Math.max(0, viewport.width - LAUNCHER_SIZE - xMargin * 2), height: Math.max(0, viewport.height - LAUNCHER_SIZE - yMargin * 2) };
}

export function launcherPosition(placement, viewport) {
  const bounds = launcherBounds(viewport), { xRatio, yRatio } = restoreLauncher(placement);
  return { x: bounds.x + bounds.width * xRatio, y: bounds.y + bounds.height * yRatio };
}

export function launcherPlacement(point, viewport) {
  const bounds = launcherBounds(viewport);
  return restoreLauncher({ xRatio: (point.x - bounds.x) / Math.max(1, bounds.width), yRatio: (point.y - bounds.y) / Math.max(1, bounds.height) });
}

export class PostConversations {
  constructor() { this.scope = null; this.generation = 0; this.entries = new Map(); }
  reset(scope = null) { this.scope = scope; this.generation++; this.entries.clear(); }
  setScope(scope) { if (scope !== this.scope) this.reset(scope); }
  entry(id) {
    if (!this.entries.has(id)) this.entries.set(id, { draft: '', turns: [], pending: false, question: '', error: '', scrollTop: null });
    return this.entries.get(id);
  }
  async send(id, request, changed = () => {}) {
    const entry = this.entry(id), originalDraft = entry.draft;
    const question = originalDraft.trim();
    if (!question || entry.pending || !this.scope) return false;
    if (question.length > 1000) { entry.error = '질문은 1,000자 이내로 적어 주세요.'; changed(); return false; }
    const generation = this.generation;
    const current = () => generation === this.generation && this.entries.get(id) === entry;
    const dialogue = entry.turns.slice(-10).map(turn => ({ ...turn, text: turn.text.slice(0, 1000) }));
    entry.pending = true; entry.question = question; entry.error = ''; entry.scrollTop = null; changed();
    try {
      const result = await request(question, dialogue);
      if (!current()) return false;
      if (typeof result?.text !== 'string' || !result.text.trim()) throw new Error('답변을 받지 못했어요. 다시 시도해 주세요.');
      entry.turns.push({ role: 'user', text: question }, { role: 'assistant', text: result.text });
      if (entry.draft === originalDraft) entry.draft = '';
      entry.scrollTop = null;
      return true;
    } catch (error) {
      if (current()) entry.error = error.message || '답변을 가져오지 못했어요. 다시 시도해 주세요.';
      return false;
    } finally {
      if (current()) { entry.pending = false; entry.question = ''; changed(); }
    }
  }
}
