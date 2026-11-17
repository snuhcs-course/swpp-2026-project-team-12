const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const relations = { father: '아버지', mother: '어머니', parent: '부모', spouse: '배우자', child: '자녀' };

// One contextual set of actions; empty relatives are never drawn around every person.
export function familyTreeActions(draft, anchorId = draft.focusedId || draft.ownerId) {
  const result = [];
  const parents = draft.parents.filter(link => link.child_id === anchorId)
    .map(link => draft.people.find(person => person.id === link.parent_id));
  if (parents.length < 2) {
    for (const [relation, gender] of [['father', 'male'], ['mother', 'female']]) {
      if (!parents.some(person => person.gender === gender)) result.push({ anchor_id: anchorId, relation });
    }
  }
  if (!draft.partnerships.some(pair => pair.first_id === anchorId || pair.second_id === anchorId)) {
    result.push({ anchor_id: anchorId, relation: 'spouse' });
  }
  const childrenOf = id => draft.parents.filter(link => link.parent_id === id).length;
  if (childrenOf(anchorId) < 10) {
    const others = draft.coParentsOf(anchorId);
    if (!others.length) result.push({ anchor_id: anchorId, relation: 'child' });
    else others.filter(id => childrenOf(id) < 10).forEach(id => result.push({ anchor_id: anchorId, relation: 'child', co_parent_id: id }));
  }
  return result;
}

// Append-only grid slots match Android. New relatives do not reflow earlier people.
export function familyTreeDrawing(draft, editable = false) {
  const nodes = [draft.people.find(person => person.id === draft.ownerId), ...draft.people.filter(person => person.id !== draft.ownerId)]
    .filter(Boolean).map(person => ({ ...person }));
  const parents = draft.parents.map(link => ({ ...link }));
  const pairs = draft.partnerships.map(link => ({ ...link }));
  const raw = new Map(), occupied = new Map();
  for (const node of nodes) {
    const partners = pairs.flatMap(pair => pair.first_id === node.id ? [raw.get(pair.second_id)] : pair.second_id === node.id ? [raw.get(pair.first_id)] : []).filter(Boolean);
    const parentPoints = parents.filter(link => link.child_id === node.id).map(link => raw.get(link.parent_id)).filter(Boolean);
    const childPoints = parents.filter(link => link.parent_id === node.id).map(link => raw.get(link.child_id)).filter(Boolean);
    const relatives = parentPoints.length ? parentPoints : childPoints;
    const desired = Math.floor((partners.length ? partners[0].x + 1 : relatives.length ? relatives.reduce((sum, point) => sum + point.x, 0) / relatives.length : 0));
    if (!occupied.has(node.generation)) occupied.set(node.generation, new Set());
    const row = occupied.get(node.generation);
    let column = desired, distance = 0;
    while (row.has(column)) { distance++; column = desired + (distance % 2 ? (distance + 1) / 2 : -distance / 2); }
    row.add(column); raw.set(node.id, { x: column, y: -node.generation });
  }
  const minX = Math.min(0, ...[...raw.values()].map(point => point.x));
  const minY = Math.min(0, ...[...raw.values()].map(point => point.y));
  const points = new Map([...raw].map(([id, point]) => [id, { x: (point.x - minX) * 144 + 72, y: (point.y - minY) * 205 + 76 }]));
  return { nodes, parents, pairs, points,
    width: Math.max(320, ...[...points.values()].map(point => point.x + 72)),
    height: Math.max(300, ...[...points.values()].map(point => point.y + 90)) };
}

export function treeMarkup(draft, { editable = false, gender, userId, members = [] } = {}) {
  const drawing = familyTreeDrawing(draft, editable);
  const line = (a, b, cls = '') => `<path class="${cls}" d="M${a.x},${a.y} L${b.x},${b.y}"/>`;
  let edges = drawing.pairs.map(pair => line(drawing.points.get(pair.first_id), drawing.points.get(pair.second_id), 'tree-spouse-line')).join('');
  const grouped = new Map();
  drawing.parents.forEach(link => { if (!grouped.has(link.child_id)) grouped.set(link.child_id, []); grouped.get(link.child_id).push(drawing.points.get(link.parent_id)); });
  grouped.forEach((parents, child) => {
    const childPoint = drawing.points.get(child);
    const center = parents.reduce((sum, point) => sum + point.x, 0) / parents.length;
    const junction = (parents[0].y + childPoint.y) / 2;
    edges += line({ x: Math.min(...parents.map(p => p.x)), y: parents[0].y }, { x: Math.max(...parents.map(p => p.x)), y: parents[0].y });
    edges += `<path d="M${center},${parents[0].y} V${junction} H${childPoint.x} V${childPoint.y}"/>`;
  });
  const cards = drawing.nodes.map((node, index) => {
    const point = drawing.points.get(node.id);
    const mine = node.user_id != null && node.user_id === userId;
    const selected = draft.selectedId === node.id;
    const claimable = editable;
    const name = node.action ? '+' : node.name || (selected ? '내 자리' : '빈자리');
    const member = members.find(member => member.person_id === node.id);
    const anchor = node.action && draft.people.find(person => person.id === node.action.anchor_id);
    const status = node.action ? `${relations[node.action.relation]} 추가` : mine ? '나' : node.user_id != null ? (member?.relationship || '가입한 가족') : '아직 가입하지 않음';
    const label = node.action ? `${anchor.name || '빈자리'}의 ${relations[node.action.relation]} 추가` : `${name} · ${status}${node.is_owner ? ' · 방장' : ''}`;
    return `<foreignObject x="${point.x - 56}" y="${point.y - 51}" width="112" height="116"><button xmlns="http://www.w3.org/1999/xhtml" type="button" class="tree-node ${node.gender} ${node.action ? 'tree-add-node' : ''} ${selected ? 'selected' : ''} ${mine ? 'mine' : ''}" data-tree-index="${index}" aria-label="${escape(label)}" title="${escape(label)}" ${editable && !node.action ? `aria-pressed="${selected}"` : ''} ${!node.action && !claimable ? 'disabled' : ''}><span class="tree-node-face">${escape(node.action ? '+' : [...name][0])}</span><strong>${escape(node.action ? relations[node.action.relation] : name)}</strong><small>${escape(status)}${node.is_owner ? ' · 방장' : ''}</small></button></foreignObject>`;
  }).join('');
  const focus = draft.people.find(person => person.id === draft.focusedId) || draft.people.find(person => person.id === draft.ownerId);
  const actions = familyTreeActions(draft, focus.id);
  const count = draft.parents.filter(link => link.parent_id === focus.id).length;
  const options = actions.map((action, index) => `<option value="${index}">${relations[action.relation]} 추가${action.relation === 'child' ? ` · ${count}/10` : ''}${action.co_parent_id && draft.coParentsOf(focus.id).length > 1 ? ` (${escape(draft.people.find(person => person.id === action.co_parent_id)?.name || '빈 가족')}와 함께)` : ''}</option>`).join('');
  const context = editable ? `<div class="tree-context"><strong>기준: ${escape(focus.name || '빈 가족')}</strong><div><select data-tree-relation aria-label="추가할 가족 관계">${options}</select><button type="button" data-tree-add ${actions.length ? '' : 'disabled'}>+ 가족 추가</button></div><small>가족을 눌러 기준을 바꿔요 · 자녀는 부모당 10명까지</small></div>` : '';
  return `<section class="family-tree-board" aria-label="${editable ? '내 자리를 선택하는 가계도' : '우리 가족 가계도'}"><div class="tree-toolbar"><span>가계도</span><div><button type="button" data-tree-zoom="out" aria-label="가계도 축소">−</button><button type="button" data-tree-zoom="in" aria-label="가계도 확대">+</button><button type="button" data-tree-zoom="fit">전체 보기</button></div></div>${context}<svg class="family-tree-canvas" viewBox="0 0 ${drawing.width} ${drawing.height}" aria-label="부모·자녀와 배우자 연결" tabindex="0">${edges}${cards}</svg><p class="tree-legend"><span>— 부모·자녀</span><span>┄ 배우자</span><span>${editable ? '가족 선택 → 관계 추가 · 빈자리는 내 자리로 선택' : '가입 전 빈자리도 함께 표시돼요'}</span></p><p class="help tree-help">드래그로 이동하고 +, − 버튼으로 확대·축소하세요. 방향키로도 이동할 수 있어요.</p></section>`;
}

export function mountTree(root, draft, { editable = false, onPerson, onAdd } = {}) {
  const drawing = familyTreeDrawing(draft, editable);
  const svg = root.querySelector('.family-tree-canvas');
  const origin = drawing.points.get(draft.ownerId);
  const saved = draft.viewport;
  let view = saved ? { x: saved.x + origin.x - saved.origin.x, y: saved.y + origin.y - saved.origin.y, width: saved.width, height: saved.height } :
    { x: origin.x - 280, y: origin.y - 180, width: 560, height: 400 };
  let pointer = null, moved = false;
  const update = () => {
    svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.width} ${view.height}`);
    draft.viewport = { ...view, origin: { ...origin } };
  };
  update();
  const zoom = factor => {
    const width = Math.max(180, Math.min(drawing.width * 2, view.width * factor));
    const scale = width / view.width;
    const height = view.height * scale;
    view = { x: view.x + (view.width - width) / 2, y: view.y + (view.height - height) / 2, width, height }; update();
  };
  root.addEventListener('click', event => {
    const control = event.target.closest('[data-tree-zoom]');
    if (control) { if (control.dataset.treeZoom === 'fit') { view = { x: 0, y: 0, width: drawing.width, height: drawing.height }; update(); } else zoom(control.dataset.treeZoom === 'in' ? .8 : 1.25); }
    if (event.target.closest('[data-tree-add]')) {
      const action = familyTreeActions(draft)[Number(root.querySelector('[data-tree-relation]').value)];
      if (action) onAdd?.(action);
      return;
    }
    const button = event.target.closest('[data-tree-index]');
    if (!button || button.disabled || (moved && event.detail)) return;
    const node = drawing.nodes[Number(button.dataset.treeIndex)];
    if (node.action) onAdd?.(node.action); else onPerson?.(node.id);
  });
  svg.addEventListener('pointerdown', event => { if (event.button !== 0) return; moved = false; pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, view: { ...view } }; });
  svg.addEventListener('pointermove', event => {
    if (!pointer || pointer.id !== event.pointerId) return;
    if (!(event.buttons & 1)) { pointer = null; return; }
    const dx = event.clientX - pointer.x, dy = event.clientY - pointer.y;
    if (!moved && Math.hypot(dx, dy) < 6) return;
    moved = true; svg.setPointerCapture(event.pointerId);
    const rect = svg.getBoundingClientRect();
    const scale = Math.max(pointer.view.width / rect.width, pointer.view.height / rect.height);
    view.x = pointer.view.x - dx * scale; view.y = pointer.view.y - dy * scale; update();
  });
  const release = () => { pointer = null; };
  svg.addEventListener('pointerup', release); svg.addEventListener('pointercancel', release);
  svg.addEventListener('keydown', event => {
    if (event.target !== svg) return;
    const shifts = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (shifts[event.key]) { event.preventDefault(); view.x += shifts[event.key][0] * view.width / 8; view.y += shifts[event.key][1] * view.height / 8; update(); }
    if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(.8); }
    if (event.key === '-') { event.preventDefault(); zoom(1.25); }
  });
}
