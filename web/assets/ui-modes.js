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
export function captionNeedsMore(caption, elder) { return !elder && String(caption || '').length > 120; }
