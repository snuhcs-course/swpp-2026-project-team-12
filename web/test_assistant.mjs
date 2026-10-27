// Offline regression checks for post selection, layout bounds and asynchronous conversation isolation.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { LAUNCHER_SIZE, centeredPost, fitPanel, launcherPlacement, launcherPosition, restoreLauncher, PostConversations } from './assets/assistant-state.js';

const viewport = { top: 80, bottom: 880, left: 0, right: 1200 };
const card = (id, top, bottom, left = 200, right = 800) => ({ id, top, bottom, left, right });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test('legacy edge positions migrate to free placement without losing their height', () => {
  assert.deepEqual(restoreLauncher({ side: 'left', ratio: .37 }), { xRatio: 0, yRatio: .37 });
  assert.deepEqual(restoreLauncher({ side: 'right', ratio: .61 }), { xRatio: 1, yRatio: .61 });
  assert.deepEqual(restoreLauncher(null), { xRatio: 1, yRatio: 1 });
});
test('interior positions round-trip without snapping; a horizontal keyboard step only moves horizontally', () => {
  const view = { left: 0, top: 0, width: 1280, height: 800 };
  const saved = launcherPlacement({ x: 512, y: 244 }, view);
  assert.ok(saved.xRatio > 0 && saved.xRatio < 1);
  const position = launcherPosition(JSON.parse(JSON.stringify(saved)), view);
  assert.ok(Math.abs(position.x - 512) < 1e-9 && Math.abs(position.y - 244) < 1e-9);
  const moved = launcherPosition(launcherPlacement({ x: position.x + 16, y: position.y }, view), view);
  assert.ok(Math.abs(moved.x - 528) < 1e-9 && Math.abs(moved.y - 244) < 1e-9);
});
test('free placement stays inside resized and offset viewports, including out-of-bounds drops', () => {
  const placement = restoreLauncher({ xRatio: .47, yRatio: .29 });
  for (const view of [{ left: 0, top: 0, width: 390, height: 844 }, { left: 40, top: 100, width: 1440, height: 700 }]) {
    for (const saved of [placement, launcherPlacement({ x: -5000, y: 5000 }, view)]) {
      const point = launcherPosition(saved, view);
      assert.ok(point.x >= view.left && point.x + LAUNCHER_SIZE <= view.left + view.width);
      assert.ok(point.y >= view.top && point.y + LAUNCHER_SIZE <= view.top + view.height);
    }
    const restored = launcherPlacement(launcherPosition(placement, view), view);
    assert.ok(Math.abs(restored.xRatio - placement.xRatio) < 1e-9);
    assert.ok(Math.abs(restored.yRatio - placement.yRatio) < 1e-9);
  }
});

test('scrolling selects the nearest visible post and excludes offscreen/filtered cards', () => {
  assert.equal(centeredPost([card(1, 100, 430), card(2, 450, 800)], viewport), 2);
  assert.equal(centeredPost([card(1, -260, 70), card(2, 90, 440), card(3, 460, 820)], viewport), 3);
  assert.equal(centeredPost([card(1, 0, 50), card(2, 900, 1100), card(3, 100, 800, 1300, 1400)], viewport), null);
  assert.equal(centeredPost([], viewport), null);
});
test('a tall post containing most of the viewport stays selected; ties retain the current post', () => {
  assert.equal(centeredPost([card(1, -1200, 800), card(2, 820, 1100)], viewport), 1);
  assert.equal(centeredPost([card(1, 280, 480), card(2, 480, 680)], viewport, 2), 2);
});
test('moving and resizing stay within the viewport, including a smaller or offset visual viewport', () => {
  for (const view of [{ width: 1280, height: 800, left: 0, top: 0 }, { width: 280, height: 250, left: 20, top: 100 }]) {
    for (const original of [{ x: -900, y: -10, width: 5000, height: 5000 }, { x: 9000, y: 3000, width: 1, height: 1 }, { x: NaN, y: 'oops', width: Infinity, height: null }]) {
      const rect = fitPanel(original, view);
      assert.ok(rect.x >= view.left && rect.y >= view.top);
      assert.ok(rect.x + rect.width <= view.left + view.width);
      assert.ok(rect.y + rect.height <= view.top + view.height);
      assert.ok(rect.width >= Math.min(320, view.width - 24));
      assert.ok(rect.height >= Math.min(300, view.height - 24));
    }
  }
});
test('late replies stay on their original post and every post preserves its own draft', async () => {
  const chats = new PostConversations(); chats.setScope('user:room');
  chats.entry(1).draft = '첫 번째 글은 어디서 찍었어?';
  const pending = deferred();
  const first = chats.send(1, (question, dialogue) => {
    assert.equal(question, '첫 번째 글은 어디서 찍었어?'); assert.deepEqual(dialogue, []); return pending.promise;
  });
  chats.entry(2).draft = '두 번째 글의 질문 초안';
  pending.resolve({ text: '첫 번째 글의 답변' }); await first;
  assert.deepEqual(chats.entry(1).turns.map(turn => turn.text), ['첫 번째 글은 어디서 찍었어?', '첫 번째 글의 답변']);
  assert.equal(chats.entry(2).draft, '두 번째 글의 질문 초안');
  assert.deepEqual(chats.entry(2).turns, []);
});
test('a pending post cannot send duplicates; replies on another post can complete independently', async () => {
  const chats = new PostConversations(); chats.setScope('user:room');
  chats.entry(1).draft = '첫 글 질문'; chats.entry(2).draft = '다음 글 질문';
  const pending = deferred(); const first = chats.send(1, () => pending.promise);
  assert.equal(await chats.send(1, () => { throw new Error('duplicate request'); }), false);
  assert.equal(await chats.send(2, async () => ({ text: '다음 글 답변' })), true);
  assert.equal(chats.entry(1).pending, true);
  pending.resolve({ text: '첫 글 답변' }); await first;
  assert.equal(chats.entry(1).pending, false);
  assert.equal(chats.entry(2).turns[1].text, '다음 글 답변');
});
test('room/account changes and logout discard drafts and in-flight replies', async () => {
  for (const nextScope of ['other-user:room', 'user:other-room', null]) {
    const chats = new PostConversations(); chats.setScope('user:room'); chats.entry(1).draft = '비공개 질문';
    const pending = deferred(); const sent = chats.send(1, () => pending.promise);
    chats.setScope(nextScope); pending.resolve({ text: '이전 가족방의 답변' }); await sent;
    assert.equal(chats.entries.size, 0);
  }
});
test('failed/empty answers retain the exact draft and a retry excludes failed turns', async () => {
  const chats = new PostConversations(); chats.setScope('user:room');
  const draft = '  실패 후 다시 물어보기  '; chats.entry(1).draft = draft;
  assert.equal(await chats.send(1, async () => { throw new Error('잠시 연결할 수 없어요.'); }), false);
  assert.equal(chats.entry(1).draft, draft); assert.equal(chats.entry(1).pending, false);
  assert.equal(await chats.send(1, async () => ({ text: '   ' })), false);
  assert.deepEqual(chats.entry(1).turns, []);
  assert.equal(await chats.send(1, async (_, dialogue) => { assert.deepEqual(dialogue, []); return { text: '복구 후 답변' }; }), true);
  assert.equal(chats.entry(1).draft, ''); assert.equal(chats.entry(1).error, '');
});
test('only the last ten successful turns are sent; edits made while waiting are preserved', async () => {
  const chats = new PostConversations(); chats.setScope('user:room');
  chats.entry(1).turns = Array.from({ length: 12 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', text: `${i}`.padEnd(1200, '.') }));
  chats.entry(1).draft = '새 질문'; const pending = deferred();
  const sent = chats.send(1, (_, dialogue) => { assert.equal(dialogue.length, 10); assert.ok(dialogue.every(turn => turn.text.length === 1000)); return pending.promise; });
  chats.entry(1).draft = '답변을 기다리며 쓴 다음 질문';
  pending.resolve({ text: '답변' }); await sent;
  assert.equal(chats.entry(1).draft, '답변을 기다리며 쓴 다음 질문');
});
