// Offline checks for device-only drafts: scoping, clearing after sending and bounded question history.
import assert from 'node:assert/strict';
import { test, beforeEach } from 'node:test';

const memory = new Map();
globalThis.localStorage = {
  get length() { return memory.size; },
  key: index => [...memory.keys()][index] ?? null,
  getItem: key => (memory.has(key) ? memory.get(key) : null),
  setItem: (key, value) => { memory.set(key, String(value)); },
  removeItem: key => { memory.delete(key); },
};
const drafts = await import('./assets/local-drafts.js');
const { PostConversations } = await import('./assets/assistant-state.js');
const escape = value => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);

beforeEach(() => memory.clear());

test('post and comment drafts belong to one account and room', () => {
  drafts.savePostDraft('7:1', '쓰다 만 소식');
  drafts.saveCommentDraft('7:1', 42, '이따 보낼 댓글');
  assert.equal(drafts.postDraft('7:1'), '쓰다 만 소식');
  assert.equal(drafts.postDraft('7:2'), '');
  assert.equal(drafts.postDraft('8:1'), '');
  assert.equal(drafts.commentDraft('7:1', 42), '이따 보낼 댓글');
  assert.equal(drafts.commentDraft('7:1', 43), '');
  drafts.savePostDraft('7:1', '   ');
  assert.equal(drafts.postDraft('7:1'), '', 'blank text removes the draft');
});

test('a sent comment clears only the draft that matches what was sent', () => {
  drafts.saveCommentDraft('7:1', 42, '보낸 댓글');
  drafts.clearCommentIfSent('7:1', 42, '다른 댓글');
  assert.equal(drafts.commentDraft('7:1', 42), '보낸 댓글');
  drafts.clearCommentIfSent('7:1', 42, ' 보낸 댓글 ');
  assert.equal(drafts.commentDraft('7:1', 42), '');
});

test('question history keeps the latest turns of the most recent posts', () => {
  for (let index = 0; index < 12; index++) drafts.rememberQuestion('7:1', 1, `질문 ${index}`, `답 ${index}`);
  const turns = drafts.pastQuestions('7:1', 1);
  assert.equal(turns.length, 20);
  assert.deepEqual(turns.slice(-2), [{ role: 'user', text: '질문 11' }, { role: 'assistant', text: '답 11' }]);
  for (let post = 2; post <= 32; post++) drafts.rememberQuestion('7:1', post, '질문', '답');
  assert.deepEqual(drafts.pastQuestions('7:1', 1), [], 'the oldest post drops out after 30');
  assert.equal(drafts.pastQuestions('7:1', 32).length, 2);
  assert.deepEqual(drafts.pastQuestions('8:1', 32), []);
});

test('earlier questions render as one collapsed, escaped toggle', () => {
  assert.equal(drafts.pastQuestionsMarkup([], escape), '');
  const markup = drafts.pastQuestionsMarkup([{ role: 'user', text: '<b>누구?</b>' }, { role: 'assistant', text: '지민이요' }], escape);
  assert.match(markup, /^<details class="past-questions"/);
  assert.doesNotMatch(markup, /<details[^>]* open/);
  assert.match(markup, /이전에 물어본 질문 1개/);
  assert.match(markup, /&lt;b&gt;누구\?&lt;\/b&gt;/);
});

test('logout forgets only that account', () => {
  drafts.savePostDraft('7:1', '내 글'); drafts.saveCommentDraft('7:2', 5, '내 댓글'); drafts.rememberQuestion('7:1', 3, '질문', '답');
  drafts.savePostDraft('17:1', '다른 사람 글');
  drafts.clearAccountDrafts(7);
  assert.equal(drafts.postDraft('7:1'), ''); assert.equal(drafts.commentDraft('7:2', 5), ''); assert.deepEqual(drafts.pastQuestions('7:1', 3), []);
  assert.equal(drafts.postDraft('17:1'), '다른 사람 글');
});

test('assistant conversations start from saved questions and send them as context', async () => {
  drafts.rememberQuestion('7:1', 9, '어디 갔어?', '속초요');
  const conversations = new PostConversations({ past: drafts.pastQuestions, remember: drafts.rememberQuestion });
  conversations.setScope('7:1');
  const entry = conversations.entry(9);
  assert.equal(entry.past.length, 2);
  assert.deepEqual(entry.turns, []);
  entry.draft = '누구랑?';
  let sent;
  assert.equal(await conversations.send(9, (question, dialogue) => { sent = dialogue; return { text: '가족이랑요' }; }), true);
  assert.deepEqual(sent.map(turn => turn.text), ['어디 갔어?', '속초요']);
  assert.equal(drafts.pastQuestions('7:1', 9).length, 4);
});

test('storage failures leave the app working without drafts', () => {
  const original = globalThis.localStorage;
  globalThis.localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); }, key() { return null; }, length: 0 };
  try {
    assert.doesNotThrow(() => drafts.savePostDraft('7:1', '글'));
    assert.equal(drafts.postDraft('7:1'), '');
    assert.deepEqual(drafts.pastQuestions('7:1', 1), []);
    assert.doesNotThrow(() => drafts.clearAccountDrafts(7));
  } finally { globalThis.localStorage = original; }
});

test('memory searches keep the newest 20 without duplicates or comment threads', () => {
  drafts.rememberMemorySearch('7:1', '카메라 누구 거야?', '도윤이 거예요', [{ id: 4, caption: '카메라', comments: [{ text: '긴 댓글' }] }]);
  drafts.rememberMemorySearch('7:1', '제주도 갔었어?', '기록이 없어요');
  drafts.rememberMemorySearch('7:1', ' 카메라 누구 거야? ', '도윤이 거예요');
  const list = drafts.memorySearches('7:1');
  assert.deepEqual(list.map(item => item.question), ['카메라 누구 거야?', '제주도 갔었어?']);
  for (let index = 0; index < 25; index++) drafts.rememberMemorySearch('7:1', `질문 ${index}`, '답');
  assert.equal(drafts.memorySearches('7:1').length, 20);
  assert.deepEqual(drafts.memorySearches('8:1'), []);
  drafts.rememberMemorySearch('7:2', '사진', '답', [{ id: 1, comments: [1, 2] }]);
  assert.equal('comments' in drafts.memorySearches('7:2')[0].posts[0], false);
  const markup = drafts.pastMemoriesMarkup(drafts.memorySearches('7:2'), escape);
  assert.match(markup, /이전에 찾아본 추억 1개/);
  assert.match(markup, /data-action="memory-past" data-index="0"/);
  drafts.clearAccountDrafts(7);
  assert.deepEqual(drafts.memorySearches('7:1'), []);
});
