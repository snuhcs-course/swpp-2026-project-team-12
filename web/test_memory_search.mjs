import assert from 'node:assert/strict';
import { test } from 'node:test';
import { memoryEvidence } from './assets/memory-search.js';

const post = id => ({ id, author_name: '지민', caption: '가족 여행', images: [{ id: 0, url: `/api/posts/${id}/images/0/` }], comment_count: 2 });
const source = (id, name) => ({ id, name });
const legacy = sources => ({ text: '부산에 다녀왔어요.', memories: [{ sources }] });

test('uses complete feed records in citation order, deduplicating repeated posts', async () => {
  const records = [post(2), post(1), post(2)];
  const result = await memoryEvidence({ evidence_posts: records }, () => assert.fail('already resolved'));
  assert.deepEqual(result, { posts: [records[0], records[1]], unavailable: false });
  assert.deepEqual(result.posts[0].images, records[0].images);
});

test('an explicitly empty evidence list never falls back to uncited retrievals', async () => {
  const result = await memoryEvidence({ ...legacy([source('a', 'post_1')]), evidence_posts: [] }, () => assert.fail('uncited request'));
  assert.deepEqual(result.posts, []);
});

test('legacy citations resolve exact episode names, respecting citation order and deduplication', async () => {
  const requests = [];
  const result = await memoryEvidence({ ...legacy([source('a', 'post_1'), source('b', 'post_2'), source('c', 'post_3')]),
    source_episode_ids: ['b', 'a', 'b'] }, async id => { requests.push(id); return post(id); });
  assert.deepEqual(requests, [2, 1]);
  assert.deepEqual(result.posts.map(item => item.id), [2, 1]);
});

test('does not infer post IDs from answer text, partial names, or invalid numbers', async () => {
  const result = await memoryEvidence({ ...legacy([
    source('a', 'some_post_1'), source('b', 'post_1_extra'), source('c', 'post_-2'),
    source('d', 'post_9007199254740993'), source('e', 'post_0'),
  ]), text: 'post_123' }, () => assert.fail('guessed post'));
  assert.deepEqual(result.posts, []);
});

test('older responses with no citations can resolve authenticated retrievals; explicit empty citations cannot', async () => {
  const data = legacy([source('a', 'post_4'), source('b', 'post_4')]);
  assert.deepEqual((await memoryEvidence(data, async id => post(id))).posts.map(item => item.id), [4]);
  assert.deepEqual((await memoryEvidence({ ...data, source_episode_ids: [] }, () => assert.fail('uncited'))).posts, []);
});

test('deleted or inaccessible posts are omitted; temporary failures keep the remaining posts', async () => {
  const result = await memoryEvidence(legacy([1, 2, 3, 4].map(id => source(String(id), `post_${id}`))), async id => {
    if (id === 1) return post(id);
    throw Object.assign(new Error('unavailable'), { status: { 2: 404, 3: 403, 4: 503 }[id] });
  });
  assert.deepEqual(result.posts.map(item => item.id), [1]);
  assert.equal(result.unavailable, true);
});

test('authentication failures propagate, and mismatched detail responses cannot become evidence', async () => {
  const data = legacy([source('a', 'post_1')]);
  await assert.rejects(memoryEvidence(data, async () => { throw Object.assign(new Error('expired'), { status: 401 }); }), /expired/);
  assert.deepEqual((await memoryEvidence(data, async () => post(2))).posts, []);
});

test('text-only or malformed legacy responses do not break answer rendering', async () => {
  for (const data of [{ text: '기록이 없어요.' }, { memories: [null, { sources: null }] }]) {
    assert.deepEqual(await memoryEvidence(data, () => assert.fail('no source')), { posts: [], unavailable: false });
  }
});
