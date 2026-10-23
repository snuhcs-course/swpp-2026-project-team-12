// Invitation drafts use the same append-only graph contract as the Android app.
export class FamilyTreeDraft {
  constructor(tree) {
    this.snapshot = structuredClone(tree);
    this.version = tree.version;
    this.ownerId = tree.owner_id;
    this.people = tree.people.map(person => ({ ...person }));
    this.parents = tree.parents.map(link => ({ ...link }));
    this.partnerships = tree.partnerships.map(link => ({ ...link }));
    this.additions = [];
    this.selectedId = null;
  }

  canClaim(id, gender) {
    const person = this.people.find(person => person.id === id);
    return Boolean(person && person.user_id == null &&
      (person.gender === 'unknown' || gender === 'unknown' || person.gender === gender));
  }

  coParentsOf(id) {
    const children = new Set(this.parents.filter(link => link.parent_id === id).map(link => link.child_id));
    const partners = this.partnerships.flatMap(link =>
      link.first_id === id ? [link.second_id] : link.second_id === id ? [link.first_id] : []);
    return [...new Set([...partners, ...this.parents
      .filter(link => link.parent_id !== id && children.has(link.child_id)).map(link => link.parent_id)])];
  }

  add(anchorId, relation, coParentId = null) {
    if (this.additions.length >= 200) throw new Error('한 번에 추가할 수 있는 가족은 200명까지예요.');
    const anchor = this.people.find(person => person.id === anchorId);
    if (!anchor || !['father', 'mother', 'parent', 'spouse', 'child'].includes(relation)) {
      throw new Error('연결할 가족과 관계를 선택해 주세요.');
    }
    const gender = relation === 'father' ? 'male' : relation === 'mother' ? 'female' : 'unknown';
    const isParent = ['father', 'mother', 'parent'].includes(relation);
    const parents = this.parents.filter(link => link.child_id === anchorId)
      .map(link => this.people.find(person => person.id === link.parent_id));
    if (isParent && (parents.length >= 2 || (gender !== 'unknown' && parents.some(person => person.gender === gender)))) {
      throw new Error('이미 등록된 부모 자리예요.');
    }
    const coParent = this.people.find(person => person.id === coParentId);
    if (coParentId && (relation !== 'child' || !coParent || coParent.generation !== anchor.generation ||
      !this.coParentsOf(anchorId).includes(coParentId))) {
      throw new Error('배우자 또는 기존 공동 부모만 함께 연결할 수 있어요.');
    }
    const id = `new_${this.additions.length + 1}`;
    const addition = { id, anchor_id: anchorId, relation };
    if (coParentId) addition.co_parent_id = coParentId;
    this.people.push({ id, name: '', gender, generation: anchor.generation + (isParent ? 1 : relation === 'child' ? -1 : 0), user_id: null });
    if (isParent) this.parents.push({ parent_id: id, child_id: anchorId });
    else if (relation === 'child') {
      this.parents.push({ parent_id: anchorId, child_id: id });
      if (coParentId) this.parents.push({ parent_id: coParentId, child_id: id });
    } else this.partnerships.push({ first_id: anchorId, second_id: id });
    this.additions.push(addition);
    this.selectedId = id;
    return id;
  }

  payload(gender) {
    if (!this.canClaim(this.selectedId, gender)) throw new Error('가계도에서 성별이 맞는 빈자리를 선택해 주세요.');
    return { tree_version: this.version, person_id: this.selectedId, additions: this.additions.map(addition => ({ ...addition })) };
  }

  undo() {
    if (!this.additions.length) return;
    const selected = this.selectedId;
    const restored = new FamilyTreeDraft(this.snapshot);
    this.additions.slice(0, -1).forEach(item => restored.add(item.anchor_id, item.relation, item.co_parent_id));
    restored.selectedId = restored.people.some(person => person.id === selected) ? selected : null;
    Object.assign(this, restored);
  }
}
