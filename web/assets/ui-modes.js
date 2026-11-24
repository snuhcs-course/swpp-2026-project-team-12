// Client-only preferences. No age inference or account-schema change is needed.
export function readMode(storage, userId) {
  try { return storage.getItem(`talkdock.web.screen:${userId}`) === 'elder' ? 'elder' : 'standard'; }
  catch { return 'standard'; }
}
export function writeMode(storage, userId, mode) {
  if (!['elder', 'standard'].includes(mode)) throw new Error('Unknown screen mode');
  try { storage.setItem(`talkdock.web.screen:${userId}`, mode); } catch { /* The current session still works. */ }
  return mode;
}
export function calendarDays(year, month) {
  // UTC arithmetic prevents browser timezone/DST changes from moving calendar cells.
  const leading = new Date(Date.UTC(year, month, 1)).getUTCDay();
  return [...Array(leading).fill(null), ...Array.from({ length: new Date(Date.UTC(year, month + 1, 0)).getUTCDate() }, (_, i) => i + 1)];
}
export function koreanDay(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}
// Use measured overflow so short text with line breaks also respects the two-line limit.
export function captionNeedsMore(scrollHeight, visibleHeight, elder) { return !elder && scrollHeight > visibleHeight + 1; }
// Rule-based closing spoken after an elderly listener hears a family post.
// The relationship label is already resolved from the viewer's side by the server.
const GENERIC_RELATIONS = new Set(['', '가족', '인척', '공동 부모 쪽 가족']);
export function replyPrompt(post, viewerId) {
  if (!post || (viewerId != null && post.author_id === viewerId)) return null;
  const relation = (post.relationship || '').trim();
  if (relation === '나' || relation === '오늘의 질문') return null;
  const name = (post.author_name || '').trim();
  const subject = !GENERIC_RELATIONS.has(relation) ? relation : name ? `${name}님` : '';
  return subject ? `${subject}의 소식에 답장해 보시는 건 어떨까요?` : null;
}
export function withReplyPrompt(text, closing) {
  const body = (text || '').trim();
  if (!closing || !body) return text;
  const ended = /[.!?…。]$/.test(body) || /[요다]$/.test(body);
  return `${body}${ended ? ' ' : '. '}${closing}`;
}
