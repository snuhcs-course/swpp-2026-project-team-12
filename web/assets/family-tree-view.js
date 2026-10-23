const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const relations = { father: '아버지', mother: '어머니', parent: '부모', spouse: '배우자', child: '자녀' };

// Match Android FamilyTreeLayout: co-parents share a block, with one row per generation.
export function familyTreeDrawing(draft, editable = false) {
  const nodes = draft.people.map(person => ({ ...person }));
  const parents = draft.parents.map(link => ({ ...link }));
  const pairs = draft.partnerships.map(link => ({ ...link }));
  const parentsOf = id => draft.parents.filter(link => link.child_id === id).map(link => link.parent_id);
  const marker = (id, generation, gender, action) => {
    nodes.push({ id, generation, gender, action });
    return id;
  };
  if (editable) {
    const childGroups = new Set();
    draft.people.forEach(person => {
      const existing = parentsOf(person.id);
      const gender = draft.people.find(node => node.id === existing[0])?.gender;
      const missing = !existing.length ? ['father', 'mother'] : existing.length === 1 ?
        [gender === 'male' ? 'mother' : gender === 'female' ? 'father' : 'parent'] : [];
      missing.forEach(relation => {
        const id = marker(`+${person.id}:${relation}`, person.generation + 1,
          relation === 'father' ? 'male' : relation === 'mother' ? 'female' : 'unknown', { anchor_id: person.id, relation });
        parents.push({ parent_id: id, child_id: person.id });
      });
      const coParents = draft.coParentsOf(person.id);
      const missingCoParent = draft.parents.some(link => link.parent_id === person.id && parentsOf(link.child_id).length === 1);
      if (!coParents.length && !missingCoParent) {
        const id = marker(`+${person.id}:spouse`, person.generation, 'unknown', { anchor_id: person.id, relation: 'spouse' });
        pairs.push({ first_id: person.id, second_id: id });
      }
      (coParents.length ? coParents : [null]).forEach(other => {
        const key = [person.id, other].filter(Boolean).sort().join(':');
        if (childGroups.has(key)) return;
        childGroups.add(key);
        const id = marker(`+child:${key}`, person.generation - 1, 'unknown',
          { anchor_id: person.id, relation: 'child', ...(other ? { co_parent_id: other } : {}) });
        parents.push({ parent_id: person.id, child_id: id });
        if (other) parents.push({ parent_id: other, child_id: id });
      });
    });
  }
  const byId = new Map(nodes.map(node => [node.id, node]));
  const groups = new Map(nodes.map(node => [node.id, node.id]));
  const root = id => { while (groups.get(id) !== id) id = groups.get(id); return id; };
  const union = (a, b) => {
    if (byId.has(a) && byId.has(b) && byId.get(a).generation === byId.get(b).generation) groups.set(root(b), root(a));
  };
  pairs.forEach(pair => union(pair.first_id, pair.second_id));
  const children = new Map();
  parents.forEach(link => { if (!children.has(link.child_id)) children.set(link.child_id, []); children.get(link.child_id).push(link.parent_id); });
  children.forEach(ids => ids.slice(1).forEach(id => union(ids[0], id)));
  const blocks = new Map();
  nodes.forEach(node => { const key = root(node.id); if (!blocks.has(key)) blocks.set(key, []); blocks.get(key).push(node); });
  blocks.forEach(block => block.sort((a, b) => ({ male: 0, unknown: 1, female: 2 }[a.gender] ?? 1) - ({ male: 0, unknown: 1, female: 2 }[b.gender] ?? 1)));
  const generations = [...new Set(nodes.map(node => node.generation))].sort((a, b) => b - a);
  const rows = generations.map(generation => [...blocks.keys()].filter(key => byId.get(key).generation === generation));
  const neighbors = new Map(nodes.map(node => [node.id, []]));
  parents.forEach(link => { neighbors.get(link.parent_id)?.push(link.child_id); neighbors.get(link.child_id)?.push(link.parent_id); });
  const x = new Map();
  const place = keys => {
    const desired = new Map(keys.map(key => {
      const values = blocks.get(key).flatMap(node => neighbors.get(node.id)).filter(id => x.has(id)).map(id => x.get(id));
      return [key, values.length ? values.reduce((a, b) => a + b, 0) / values.length : [...blocks.keys()].indexOf(key) * 170];
    }));
    const ordered = [...keys].sort((a, b) => desired.get(a) - desired.get(b));
    const centers = new Map();
    let right = -Infinity;
    ordered.forEach(key => { const half = blocks.get(key).length * 66; const center = Math.max(desired.get(key), right + 36 + half); centers.set(key, center); right = center + half; });
    const shift = ordered.reduce((sum, key) => sum + centers.get(key) - desired.get(key), 0) / (ordered.length || 1);
    ordered.forEach(key => blocks.get(key).forEach((node, index, block) => x.set(node.id, centers.get(key) - shift + (index - (block.length - 1) / 2) * 132)));
  };
  rows.forEach(place);
  for (let i = 0; i < 4; i++) { [...rows].reverse().forEach(place); rows.forEach(place); }
  const minX = x.size ? Math.min(...x.values()) : 0;
  const points = new Map(nodes.map(node => [node.id, { x: x.get(node.id) - minX + 72, y: (generations[0] - node.generation) * 205 + 76 }]));
  return { nodes, parents, pairs, points, width: Math.max(248, ...[...points.values()].map(point => point.x + 72)), height: Math.max(260, ...[...points.values()].map(point => point.y + 90)) };
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
    const claimable = editable && draft.canClaim(node.id, gender);
    const name = node.action ? '+' : node.name || (selected ? '내 자리' : '빈자리');
    const member = members.find(member => member.person_id === node.id);
    const anchor = node.action && draft.people.find(person => person.id === node.action.anchor_id);
    const status = node.action ? `${relations[node.action.relation]} 추가` : mine ? '나' : node.user_id != null ? (member?.relationship || '가입한 가족') : '아직 가입하지 않음';
    const label = node.action ? `${anchor.name || '빈자리'}의 ${relations[node.action.relation]} 추가` : `${name} · ${status}${node.is_owner ? ' · 방장' : ''}`;
    return `<foreignObject x="${point.x - 56}" y="${point.y - 51}" width="112" height="116"><button xmlns="http://www.w3.org/1999/xhtml" type="button" class="tree-node ${node.gender} ${node.action ? 'tree-add-node' : ''} ${selected ? 'selected' : ''} ${mine ? 'mine' : ''}" data-tree-index="${index}" aria-label="${escape(label)}" title="${escape(label)}" ${editable && !node.action ? `aria-pressed="${selected}"` : ''} ${!node.action && !claimable ? 'disabled' : ''}><span class="tree-node-face">${escape(node.action ? '+' : [...name][0])}</span><strong>${escape(node.action ? relations[node.action.relation] : name)}</strong><small>${escape(status)}${node.is_owner ? ' · 방장' : ''}</small></button></foreignObject>`;
  }).join('');
  return `<section class="family-tree-board" aria-label="${editable ? '내 자리를 선택하는 가계도' : '우리 가족 가계도'}"><div class="tree-toolbar"><span>가계도</span><div><button type="button" data-tree-zoom="out" aria-label="가계도 축소">−</button><button type="button" data-tree-zoom="in" aria-label="가계도 확대">+</button><button type="button" data-tree-zoom="fit">전체 보기</button></div></div><svg class="family-tree-canvas" viewBox="0 0 ${drawing.width} ${drawing.height}" aria-label="부모·자녀와 배우자 연결" tabindex="0">${edges}${cards}</svg><p class="tree-legend"><span>— 부모·자녀</span><span>┄ 배우자</span><span>${editable ? '+ 가족 추가 · 빈자리 선택' : '가입 전 빈자리도 함께 표시돼요'}</span></p><p class="help tree-help">드래그로 이동하고 +, − 버튼으로 확대·축소하세요. 방향키로도 이동할 수 있어요.</p></section>`;
}

export function mountTree(root, draft, { editable = false, onPerson, onAdd } = {}) {
  const drawing = familyTreeDrawing(draft, editable);
  const svg = root.querySelector('.family-tree-canvas');
  let view = { x: 0, y: 0, width: drawing.width, height: drawing.height };
  let pointer = null, moved = false;
  const update = () => svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.width} ${view.height}`);
  const zoom = factor => {
    const width = Math.max(180, Math.min(drawing.width * 2, view.width * factor));
    const scale = width / view.width;
    const height = view.height * scale;
    view = { x: view.x + (view.width - width) / 2, y: view.y + (view.height - height) / 2, width, height }; update();
  };
  root.addEventListener('click', event => {
    const control = event.target.closest('[data-tree-zoom]');
    if (control) { if (control.dataset.treeZoom === 'fit') { view = { x: 0, y: 0, width: drawing.width, height: drawing.height }; update(); } else zoom(control.dataset.treeZoom === 'in' ? .8 : 1.25); }
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
  if (drawing.width > 850 || drawing.height > 600) {
    const focus = drawing.points.get(draft.selectedId || draft.ownerId);
    if (focus) { view = { x: focus.x - 425, y: focus.y - 260, width: 850, height: 520 }; update(); }
  }
}
