import test from 'node:test';
import assert from 'node:assert/strict';
import { VoicePreview } from './assets/voice-preview.js';

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
test('voice selection discards stale downloads and reuses the preloaded sample', async () => {
  const a = deferred(), b = deferred(), loads = [], played = [];
  let selected = 'a';
  const preview = new VoicePreview({ load: key => { loads.push(key); return key === 'a' ? a.promise : b.promise; },
    play: async blob => played.push(blob), stop() {}, status() {}, current: key => selected === key });
  preview.preload('a'); const old = preview.preview('a');
  selected = 'b'; preview.cancel(); preview.preload('b'); const next = preview.preview('b');
  b.resolve('B'); await next; a.resolve('A'); await old;
  assert.deepEqual(played, ['B']); assert.deepEqual(loads, ['a', 'b']);
  await preview.preview('b'); assert.deepEqual(loads, ['a', 'b']);
});
test('leaving the page prevents late playback and a failed preload can be retried', async () => {
  const pending = deferred(); let connected = true, count = 0, message = '';
  const preview = new VoicePreview({ load: () => ++count === 1 ? Promise.reject(Error()) : pending.promise,
    play: async () => assert.fail('stale sample played'), stop() {}, status: value => { message = value; }, current: () => connected });
  await preview.preview('a'); assert.match(message, /다시/);
  const retry = preview.preview('a'); connected = false; preview.cancel(); pending.resolve('audio'); await retry;
  assert.equal(count, 2); assert.equal(message, '');
});
