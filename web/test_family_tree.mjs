import assert from 'node:assert/strict';
import test from 'node:test';
import { FamilyTreeDraft } from './assets/family-tree.js';

const snapshot = () => ({
  version: 3, owner_id: '1',
  people: [
    { id: '1', name: '지민', gender: 'female', generation: 0, user_id: 10 },
    { id: '2', name: '', gender: 'unknown', generation: -1, user_id: null },
  ],
  parents: [{ parent_id: '1', child_id: '2' }], partnerships: [],
});

test('claim an existing empty person with the snapshot version and no additions', () => {
  const draft = new FamilyTreeDraft(snapshot());
  draft.selectedId = '2';
  assert.deepEqual(draft.payload('male'), { tree_version: 3, person_id: '2', additions: [] });
});

test('build sequential relatives through unclaimed people without changing the server snapshot', () => {
  const tree = snapshot();
  const original = structuredClone(tree);
  const draft = new FamilyTreeDraft(tree);
  const parent = draft.add('1', 'mother');
  const grandma = draft.add(parent, 'mother');
  assert.equal(draft.people.find(person => person.id === grandma).generation, 2);
  assert.deepEqual(draft.payload('female').additions.map(addition => addition.anchor_id), ['1', parent]);
  assert.deepEqual(tree, original);
  assert.equal(draft.canClaim(grandma, 'male'), false);
});

test('allow multiple children and link a new child to both parents', () => {
  const draft = new FamilyTreeDraft(snapshot());
  const spouse = draft.add('1', 'spouse');
  const first = draft.add('1', 'child', spouse);
  const second = draft.add('1', 'child', spouse);
  assert.notEqual(first, second);
  assert.deepEqual(draft.coParentsOf('1'), [spouse]);
  assert.equal(draft.parents.filter(link => link.child_id === second).length, 2);
  assert.equal(draft.payload('female').additions.at(-1).co_parent_id, spouse);
});

test('reject occupied people and gender mismatches', () => {
  const draft = new FamilyTreeDraft(snapshot());
  draft.selectedId = '1';
  assert.throws(() => draft.payload('female'), /빈자리/);
  const father = draft.add('1', 'father');
  assert.equal(draft.canClaim(father, 'female'), false);
  assert.throws(() => draft.payload('female'), /빈자리/);
});

test('reject invalid additions before mutating the draft', () => {
  const draft = new FamilyTreeDraft(snapshot());
  draft.add('1', 'father');
  const before = JSON.stringify(draft);
  assert.throws(() => draft.add('1', 'father'), /부모/);
  assert.throws(() => draft.add('1', 'child', '2'), /공동 부모/);
  assert.throws(() => draft.add('missing', 'child'), /선택/);
  assert.throws(() => draft.add('1', 'sibling'), /선택/);
  assert.equal(JSON.stringify(draft), before);
});

test('enforce the same 200-person invitation limit as the backend and Android', () => {
  const draft = new FamilyTreeDraft(snapshot());
  for (let index = 0; index < 200; index++) draft.add('1', 'child');
  assert.equal(draft.payload('male').additions.length, 200);
  assert.throws(() => draft.add('1', 'child'), /200/);
});
