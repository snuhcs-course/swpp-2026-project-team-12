"""Find relationships from the room's parent/child and partnership graph."""

from collections import defaultdict
from heapq import heappop, heappush
from itertools import combinations, count


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
    graph = defaultdict(set)
    parents = defaultdict(set)
    for link in tree["parents"]:
        parent, child = link["parent_id"], link["child_id"]
        if parent in people and child in people:
            graph[child].add(("up", parent))
            graph[parent].add(("down", child))
            parents[child].add(parent)
    for link in tree["partnerships"]:
        first, second = link["first_id"], link["second_id"]
        if first in people and second in people:
            graph[first].add(("spouse", second))
            graph[second].add(("spouse", first))
    if ("spouse", destination) in graph[source]:
        return _spouse(people[destination]["gender"])

    # Sharing a child establishes co-parenthood, not a marriage. These virtual
    # edges also prevent a detour through a child from masquerading as lineage.
    for co_parents in parents.values():
        for first, second in combinations(sorted(co_parents), 2):
            if ("spouse", second) not in graph[first]:
                graph[first].add(("co_parent", second))
                graph[second].add(("co_parent", first))

    path = _find_path(graph, source, destination)
    if path is None:
        return "가족"
    affinities = [step for step, _ in path if step in ("spouse", "co_parent")]
    fallback = "공동 부모 쪽 가족" if "co_parent" in affinities else "인척"
    # Bound composition before recursing, including unusually large trees.
    if len(affinities) > 3:
        return fallback
    label = _describe(path, people)
    return fallback if label.count("의 ") > 2 else label


def _find_path(graph, source, destination):
    # Prefer blood relationships over shortcuts through partners or shared
    # children, then the shortest path. Stable ties do not depend on DB order.
    sequence = count()
    queue = [((0, 0, 0), next(sequence), source, False, ())]
    best = {(source, False): (0, 0, 0)}
    while queue:
        cost, _, current, descending, path = heappop(queue)
        if best[current, descending] != cost:
            continue
        if current == destination:
            return path
        for direction, neighbor in sorted(graph[current]):
            # A blood segment can go up to an ancestor and then down, but never
            # down and back up to an unrelated parent. Affinity starts a segment.
            if neighbor == source or (direction == "up" and descending):
                continue
            affinity = direction in ("spouse", "co_parent")
            next_descending = direction == "down"
            next_cost = (cost[0] + affinity, cost[1] + 1,
                         cost[2] + (direction == "co_parent"))
            state = (neighbor, next_descending)
            if state in best and best[state] <= next_cost:
                continue
            best[state] = next_cost
            heappush(queue, (next_cost, next(sequence), neighbor, next_descending,
                             path + ((direction, neighbor),)))
    return None


def _lineage(direction, distance, gender):
    if distance > (4 if direction == "up" else 3):
        return f"{distance}대 " + ("조상" if direction == "up" else "후손")
    names = {
        "up": (("아버지", "어머니", "부모"), ("할아버지", "할머니", "조부모"),
               ("증조할아버지", "증조할머니", "증조부모"), ("고조할아버지", "고조할머니", "고조부모")),
        "down": (("아들", "딸", "자녀"), ("손자", "손녀", "손주"),
                 ("증손자", "증손녀", "증손주")),
    }
    return names[direction][distance - 1][{"male": 0, "female": 1}.get(gender, 2)]


def _spouse(gender):
    return {"male": "남편", "female": "아내"}.get(gender, "배우자")


def _describe(path, people):
    for index, (direction, partner) in enumerate(path):
        if direction not in ("spouse", "co_parent"):
            continue
        before, after = path[:index], path[index + 1:]
        prefix = _blood_relationship(before, people) if before else None
        if direction == "co_parent":
            label = "의 ".join(part for part in (prefix, "공동 부모") if part)
        else:
            partner_gender = people[partner]["gender"]
            label = "의 ".join(part for part in (prefix, _spouse(partner_gender)) if part)
            if not before and len(after) == 1 and after[0][0] == "up":
                parent_gender = people[after[0][1]]["gender"]
                names = {"male": {"male": "시아버지", "female": "시어머니"},
                         "female": {"male": "장인", "female": "장모"}}
                return names.get(partner_gender, {}).get(
                    parent_gender, label + "의 " + _lineage("up", 1, parent_gender))
            if len(before) == 1 and before[0][0] == "down":
                if len(after) == 1 and after[0][0] == "up":
                    return "사돈"
                child_gender = people[before[0][1]]["gender"]
                label = {("male", "female"): "며느리", ("female", "male"): "사위"}.get(
                    (child_gender, partner_gender), label)
            # 숙모/큰어머니 requires the paternal uncle's relative age, which
            # the tree does not collect. Keep "삼촌의 아내" in that case.
            if prefix == "외삼촌" and partner_gender == "female":
                label = "외숙모"
            elif prefix in ("고모", "이모") and partner_gender == "male":
                label = "고모부" if prefix == "고모" else "이모부"
        return label + "의 " + _describe(after, people) if after else label
    return _blood_relationship(path, people)


def _blood_relationship(path, people):
    steps = tuple(direction for direction, _ in path)
    up, down = steps.count("up"), steps.count("down")
    gender = people[path[-1][1]]["gender"]
    if not up or not down:
        prefix = "외" if (steps[0] == "up" and 2 <= up <= 4
                         and people[path[0][1]]["gender"] == "female") else ""
        return prefix + _lineage(steps[0], len(path), gender)
    if up == down == 1:
        return "형제자매"
    if up == 1:
        return "조카" if down == 2 else "조카의 " + _lineage("down", down - 2, gender)
    if down == 1:
        if up == 2:
            parent_gender = people[path[0][1]]["gender"]
            names = {"male": {"male": "삼촌", "female": "고모"},
                     "female": {"male": "외삼촌", "female": "이모"}}
            return names.get(parent_gender, {}).get(
                gender, _blood_relationship(path[:1], people) + "의 형제자매")
        return _blood_relationship(path[:up - 1], people) + "의 형제자매"
    degree = up + down
    return "사촌" if degree == 4 else f"{degree}촌 친척"
