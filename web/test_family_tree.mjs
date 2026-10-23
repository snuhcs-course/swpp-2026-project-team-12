import assert from 'node:assert/strict';
import test from 'node:test';
import { FamilyTreeDraft } from './assets/family-tree.js';
import { familyTreeDrawing, treeMarkup } from './assets/family-tree-view.js';

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

test('undo removes dependent edges while preserving an earlier selected position', () => {
  const draft = new FamilyTreeDraft(snapshot());
  const spouse = draft.add('1', 'spouse');
  draft.add('1', 'child', spouse);
  draft.selectedId = spouse;
  draft.undo();
  assert.equal(draft.selectedId, spouse);
  assert.equal(draft.people.length, 3);
  assert.equal(draft.parents.length, 1);
  draft.undo();
  assert.equal(draft.selectedId, null);
  assert.deepEqual(draft.people, snapshot().people);
  assert.deepEqual(draft.partnerships, []);
});

test('read-only tree includes unclaimed people and places ancestors above children', () => {
  const draft = new FamilyTreeDraft(snapshot());
  const drawing = familyTreeDrawing(draft);
  assert.equal(drawing.nodes.length, 2);
  assert.ok(drawing.points.get('1').y < drawing.points.get('2').y);
  assert.equal(drawing.nodes.some(node => node.action), false);
  assert.match(treeMarkup(draft), /아직 가입하지 않음/);
});

test('editable frontier matches Android missing parents and shared child actions', () => {
  const draft = new FamilyTreeDraft(snapshot());
  const spouse = draft.add('1', 'spouse');
  const drawing = familyTreeDrawing(draft, true);
  const children = drawing.nodes.filter(node => node.action?.relation === 'child');
  assert.equal(children.filter(node => node.action.anchor_id === '1' && node.action.co_parent_id === spouse).length, 1);
  const child = children.find(node => node.action.co_parent_id === spouse);
  assert.equal(drawing.parents.filter(link => link.child_id === child.id).length, 2);
  assert.equal(drawing.nodes.filter(node => node.action?.anchor_id === '2' && node.action?.relation === 'father').length, 1);
  assert.equal(drawing.nodes.filter(node => node.action?.anchor_id === '2' && node.action?.relation === 'mother').length, 0);
});

test('large editable families have no overlapping node cards or missing connector endpoints', () => {
  const draft = new FamilyTreeDraft(snapshot());
  const spouse = draft.add('1', 'spouse');
  for (let i = 0; i < 10; i++) draft.add('1', 'child', spouse);
  const drawing = familyTreeDrawing(draft, true);
  for (const a of drawing.nodes) for (const b of drawing.nodes) {
    if (a.id === b.id || a.generation !== b.generation) continue;
    assert.ok(Math.abs(drawing.points.get(a.id).x - drawing.points.get(b.id).x) >= 112);
  }
  drawing.parents.forEach(link => { assert.ok(drawing.points.has(link.parent_id)); assert.ok(drawing.points.has(link.child_id)); });
  assert.ok([...drawing.points.values()].every(point => Number.isFinite(point.x) && Number.isFinite(point.y)));
});

test('tree cards escape names supplied by accounts', () => {
  const draft = new FamilyTreeDraft(snapshot());
  draft.people[0].name = '<img src=x onerror=alert(1)>';
  const html = treeMarkup(draft);
  assert.ok(!html.includes('<img'));
  assert.match(html, /&lt;img/);
});
