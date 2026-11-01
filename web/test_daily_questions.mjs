// Run: node --test web/test_daily_questions.mjs (offline).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { answerChoice, questionEntry, questionHistory, questionMarkup, questionPayload, questionVersion } from './assets/daily-questions.js';

const question = (kind = 'choice', options = ['산책', '쉬기', '기타']) => ({
  id: 31, date: '2026-10-31', version: '31:a:b', kind, title: '가족과 무엇을 할까요?', options, answers: [], comments: [],
});

test('custom choice text is separate from the reason and cleared for regular choices', () => {
  const draft = { choice: '기타', other_text: ' 요리 ', text: ' 함께하고 싶어요 ', source: 'voice' };
  assert.deepEqual(questionPayload(question(), draft), { choice: '기타', other_text: '요리', text: '함께하고 싶어요', tiers: {}, source: 'voice' });
  assert.equal(questionPayload(question(), { ...draft, choice: '산책' }).other_text, '');
  assert.equal(answerChoice({ choice: '기타', other_text: '요리' }), '기타 · 요리');
});

test('invalid answers cannot be submitted, including empty or oversized custom content', () => {
  for (const draft of [{}, { choice: '없는 항목' }, { choice: '기타' }, { choice: '기타', other_text: ' ' },
    { choice: '기타', other_text: '가'.repeat(101) }, { choice: '산책', text: '가'.repeat(1001) }]) {
    assert.throws(() => questionPayload(question(), draft));
  }
  assert.throws(() => questionPayload(question('text', []), { text: ' ' }));
});

test('text, weather and all tier grades produce the API payload without stale fields', () => {
  assert.deepEqual(questionPayload(question('text', []), { choice: '산책', other_text: '요리', text: ' 옛 추억 ', tiers: { 산책: 'S' } }),
    { choice: '', other_text: '', text: '옛 추억', tiers: {}, source: 'text' });
  assert.equal(questionPayload(question('weather', ['맑음', '비', '기타']), { choice: '비' }).choice, '비');
  const tiers = question('tier', ['산책', '요리']);
  assert.throws(() => questionPayload(tiers, { tiers: { 산책: 'S' } }));
  assert.throws(() => questionPayload(tiers, { tiers: { 산책: 'S', 요리: 'Z' } }));
  assert.deepEqual(questionPayload(tiers, { tiers: { 산책: 'S', 요리: 'S' } }).tiers, { 산책: 'S', 요리: 'S' });
  assert.equal(questionPayload(question('tier', ['__proto__', '요리']), { tiers: JSON.parse('{"__proto__":"A","요리":"B"}') }).tiers.__proto__, 'A');
});

test('saved answers retain every choice and expose editing without per-answer discussion', () => {
  const data = question();
  data.answers = [{ author_id: 1, author_name: '정아', choice: '기타', other_text: '요리', text: '함께해요', tiers: {} }];
  const markup = questionMarkup(data, 1);
  assert.equal((markup.match(/type="radio"/g) || []).length, 3);
  assert.equal((markup.match(/disabled/g) || []).length, 3);
  assert.match(markup, /daily-edit/);
  assert.match(markup, /기타 · 요리/);
  assert.doesNotMatch(markup, /data-form="daily-answer"|이 답변에 대해 이야기/);
  const editor = questionMarkup(data, 1, { editing: true, draft: data.answers[0] });
  assert.match(editor, /name="other_text"[^>]+value="요리"[^>]+required/);
  assert.match(editor, /data-form="daily-comment"/);
});

test('question, answers, options, comments and history escape user-controlled text', () => {
  const bad = '<img src=x onerror=alert(1)>';
  const data = question('choice', [bad, '기타']);
  data.title = bad;
  data.answers = [{ author_id: 2, author_name: bad, choice: bad, text: bad, tiers: {} }];
  data.comments = [{ author_name: bad, text: bad }];
  for (const markup of [questionMarkup(data, 1), questionEntry(data), questionHistory([data], null)]) {
    assert.doesNotMatch(markup, /<img/);
    assert.match(markup, /&lt;img/);
  }
});

test('history supports pagination and entry versions detect new family activity', () => {
  const data = question();
  assert.match(questionHistory([data], '2026-10-01'), /data-before="2026-10-01"/);
  assert.doesNotMatch(questionHistory([data], null), /daily-more/);
  assert.match(questionEntry(data, true), /daily-unread/);
  assert.doesNotMatch(questionEntry(data, false), /class="daily-unread"/);
  assert.equal(questionVersion(data), '2026-10-31|31:a:b');
});
