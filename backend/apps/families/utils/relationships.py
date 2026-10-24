"""Find relationships from the room's parent/child and partnership graph."""

from collections import defaultdict, deque


def relationship(viewer, target, room):
    """Return target's relationship to viewer, including through unclaimed people."""
    from .tree import tree_data

    members = dict(room.members.filter(user_id__in=(viewer.pk, target.pk))
                   .values_list("user_id", "person_id"))
    return find_relationship(tree_data(room), str(members.get(viewer.pk)), str(members.get(target.pk)))


def find_relationship(tree, source, destination):
    """Search a tree snapshot by person ID; independent of accounts and the ORM."""
    people = {person["id"]: person for person in tree["people"]}
    if source not in people or destination not in people:
        return "가족"
    if source == destination:
        return "나"
    graph = defaultdict(list)
    for link in tree["parents"]:
        parent, child = link["parent_id"], link["child_id"]
        if parent in people and child in people:
            graph[child].append(("up", parent))
            graph[parent].append(("down", child))
    for link in tree["partnerships"]:
        first, second = link["first_id"], link["second_id"]
        if first in people and second in people:
            graph[first].append(("spouse", second))
            graph[second].append(("spouse", first))
    queue = deque([(source, ())])
    visited = {source}
    while queue:
        current, path = queue.popleft()
        for direction, neighbor in graph[current]:
            if neighbor in visited:
                continue
            next_path = path + ((direction, neighbor),)
            if neighbor == destination:
                return _describe(next_path, people)
            visited.add(neighbor)
            queue.append((neighbor, next_path))
    return "가족"


def _lineage(direction, distance, gender):
    if distance > 2:
        return f"{distance}대 " + ("조상" if direction == "up" else "후손")
    names = {
        "up": (("아버지", "어머니", "부모"), ("할아버지", "할머니", "조부모")),
        "down": (("아들", "딸", "자녀"), ("손자", "손녀", "손주")),
    }
    return names[direction][distance - 1][{"male": 0, "female": 1}.get(gender, 2)]


def _describe(path, people):
    # Compose in-law relationships from the actual path rather than owner roles.
    for index, (direction, _) in enumerate(path):
        if direction == "spouse":
            parts = [_describe(path[:index], people)] if index else []
            parts.append("배우자")
            if index + 1 < len(path):
                parts.append(_describe(path[index + 1:], people))
            return "의 ".join(parts)
    steps = tuple(direction for direction, _ in path)
    up, down = steps.count("up"), steps.count("down")
    gender = people[path[-1][1]]["gender"]
    if not up or not down:
        prefix = "외" if steps == ("up", "up") and people[path[0][1]]["gender"] == "female" else ""
        return prefix + _lineage(steps[0], len(path), gender)
    if steps != ("up",) * up + ("down",) * down:
        return "의 ".join(_lineage(direction, 1, people[person]["gender"]) for direction, person in path)
    if up == down == 1:
        return "형제자매"
    if up == 1:
        return "조카" if down == 2 else "형제자매의 " + _lineage("down", down - 1, gender)
    if down == 1:
        return _lineage("up", up - 1, "unknown") + "의 형제자매"
    degree = up + down
    return "사촌" if degree == 4 else f"{degree}촌 친척"
