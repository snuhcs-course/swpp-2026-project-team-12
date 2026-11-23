// Device-only drafts: the unfinished post text, unsent comments and past questions to Todak.
// Nothing here is sent to the server. Every entry belongs to one account and family room
// (`${user_id}:${room_id}`), so switching accounts in one browser never shows another person's text.
// Storage can be missing or full (private windows, blocked site data); every call then degrades to "nothing saved".
const PREFIX = 'talkdock-drafts:';
const MAX_TEXT = 2000, MAX_ANSWER = 4000, MAX_TURNS = 10, MAX_POSTS = 30;

function read(key, fallback) {
  try { const raw = localStorage.getItem(PREFIX + key); return raw == null ? fallback : JSON.parse(raw); } catch { return fallback; }
}
function write(key, value) {
  try { if (value == null) localStorage.removeItem(PREFIX + key); else localStorage.setItem(PREFIX + key, JSON.stringify(value)); } catch { /* not saved */ }
}

export function postDraft(scope) { return scope ? read(`post:${scope}`, '') : ''; }
export function savePostDraft(scope, text) { if (scope) write(`post:${scope}`, text.trim() ? text.slice(0, MAX_TEXT) : null); }
export function clearPostDraft(scope) { if (scope) write(`post:${scope}`, null); }

export function commentDraft(scope, postId) { return scope ? read(`comment:${scope}:${postId}`, '') : ''; }
export function saveCommentDraft(scope, postId, text) { if (scope) write(`comment:${scope}:${postId}`, text.trim() ? text.slice(0, MAX_TEXT) : null); }
/** A finished send removes the draft only if it is still the text that was sent. */
export function clearCommentIfSent(scope, postId, sent) {
  if (scope && commentDraft(scope, postId).trim() === String(sent).trim()) saveCommentDraft(scope, postId, '');
}

/** Earlier turns for a post, as [{ role: 'user' | 'assistant', text }]. */
export function pastQuestions(scope, postId) {
  const entry = scope ? read(`questions:${scope}`, {})[postId] : null;
  return Array.isArray(entry?.turns) ? entry.turns.filter(turn => turn && typeof turn.text === 'string' && ['user', 'assistant'].includes(turn.role)) : [];
}
/** Keeps the latest turns of the most recently asked posts; the oldest posts drop out first. */
export function rememberQuestion(scope, postId, question, answer) {
  if (!scope) return;
  const book = read(`questions:${scope}`, {});
  const turns = [...pastQuestions(scope, postId), { role: 'user', text: question.slice(0, MAX_TEXT) }, { role: 'assistant', text: answer.slice(0, MAX_ANSWER) }];
  book[postId] = { at: Date.now(), turns: turns.slice(-MAX_TURNS * 2) };
  Object.keys(book).sort((a, b) => (book[b]?.at || 0) - (book[a]?.at || 0)).slice(MAX_POSTS).forEach(id => { delete book[id]; });
  write(`questions:${scope}`, book);
}

/** Explicit logout: forget this account's drafts in this browser. */
export function clearAccountDrafts(userId) {
  try {
    const names = [];
    for (let index = 0; index < localStorage.length; index++) {
      const name = localStorage.key(index);
      if (name?.startsWith(PREFIX) && name.slice(PREFIX.length).split(':')[1] === String(userId)) names.push(name);
    }
    names.forEach(name => localStorage.removeItem(name));
  } catch { /* nothing to clear */ }
}

/** One collapsed toggle with the earlier questions, instead of listing them all. */
export function pastQuestionsMarkup(turns, escape, labels = { user: '나', assistant: '토닥' }) {
  const asked = turns.filter(turn => turn.role === 'user').length;
  if (!asked) return '';
  const items = turns.map(turn => `<div class="past-turn ${turn.role}"><span>${labels[turn.role]}</span><p>${escape(turn.text)}</p></div>`).join('');
  return `<details class="past-questions" data-past-questions><summary>이전에 물어본 질문 ${asked}개</summary><div class="past-question-list">${items}</div></details>`;
}
