import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readMode, writeMode, calendarDays, koreanDay, captionNeedsMore } from './assets/ui-modes.js';
test('screen choices belong to each account and never use age or another account choice', () => {
  const data = new Map(); const storage={getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)};
  assert.equal(readMode(storage,1),'standard');
  writeMode(storage,1,'elder'); assert.equal(readMode(storage,1),'elder'); assert.equal(readMode(storage,2),'standard');
  writeMode(storage,2,'standard'); assert.equal(readMode(storage,1),'elder');
  assert.throws(()=>writeMode(storage,1,'unknown'));
});
test('blocked browser storage leaves the current mode usable', () => {
  const storage={getItem(){throw Error('blocked')},setItem(){throw Error('blocked')}};
  assert.equal(readMode(storage,1),'standard'); assert.equal(writeMode(storage,1,'elder'),'elder');
});
test('calendar preserves Sunday-first alignment and leap days', () => {
  const leap=calendarDays(2028,1); assert.equal(leap.filter(Boolean).length,29); assert.equal(leap[0],null); assert.equal(leap[2],1);
  const sunday=calendarDays(2026,10); assert.equal(sunday[0],1); assert.equal(sunday.at(-1),30);
});
test('day membership uses Korean midnight rather than the browser timezone', () => {
  assert.equal(koreanDay('2026-11-08T14:59:59Z'),'2026-11-08');
  assert.equal(koreanDay('2026-11-08T15:00:00Z'),'2026-11-09');
  assert.equal(koreanDay('invalid'),'');
});
test('caption expansion follows measured two-line overflow and preserves elderly full text', () => {
  assert.equal(captionNeedsMore(90,60,false),true);
  assert.equal(captionNeedsMore(90,60,true),false);
  assert.equal(captionNeedsMore(60,60,false),false);
  assert.equal(captionNeedsMore(0,0,false),false);
  assert.equal(captionNeedsMore(60.5,60,false),false);
});
