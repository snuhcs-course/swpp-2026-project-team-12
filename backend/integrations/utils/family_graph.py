"""Project the SQL family tree into Graphiti without LLM identity decisions."""

from collections import Counter
from uuid import NAMESPACE_URL, uuid5

from django.db import transaction
from django.utils import timezone
from graphiti_core.edges import EntityEdge, EpisodicEdge
from graphiti_core.nodes import EntityNode, EpisodeType, EpisodicNode

from apps.families.models import FamilyPerson, FamilyRoom
from apps.families.utils.relationships import find_relationship
from apps.families.utils.tree import tree_data

from integrations.ai_workers.graphiti_client import family_group


def graph_uuid(key):
    return str(uuid5(NAMESPACE_URL, f"talkdock:{key}"))


def sync_family(graphiti, family_id, runner):
    # The version gap is a durable job; a concurrent join leaves another gap.
    with transaction.atomic():
        room = FamilyRoom.objects.get(pk=family_id)
        if room.graph_synced_version == room.tree_version:
            return
        tree = tree_data(room)
        links = {str(p.pk): str(p.graphiti_uuid) if p.graphiti_uuid else None
                 for p in room.people.all()}
    mapping = runner.run(construct_family(graphiti, family_id, tree, links))
    with transaction.atomic():
        for person_id, node_uuid in mapping.items():
            FamilyPerson.objects.filter(pk=person_id, room_id=family_id).update(graphiti_uuid=node_uuid)
        FamilyRoom.objects.filter(pk=family_id).update(graph_synced_version=tree["version"])


async def construct_family(graphiti, family_id, tree, links):
    group = family_group(family_id)
    people = [p for p in tree["people"] if p["user_id"] is not None]
    names = Counter(p["name"] for p in people)
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (n:Entity {group_id: $group}) "
        "WHERE n.uuid IN $uuids OR n.family_person_id IN $ids OR n.name IN $names "
        "RETURN n.uuid AS uuid",
        group=group, uuids=[u for u in links.values() if u],
        ids=[int(p["id"]) for p in people], names=list(names), routing_="r",
    )
    nodes = await graphiti.nodes.entity.get_by_uuids([r["uuid"] for r in records]) if records else []
    nodes = [n for n in nodes if n.group_id == group]
    mapping = {}
    now = timezone.now()
    for person in people:
        person_id = person["id"]
        node = next((n for n in nodes if n.uuid == links[person_id]
                     or n.attributes.get("family_person_id") == int(person_id)), None)
        if node is None and links[person_id] is None and names[person["name"]] == 1:
            matches = [n for n in nodes if n.name == person["name"]
                       and n.attributes.get("family_person_id") is None
                       and n.uuid not in links.values() and n.uuid not in mapping.values()]
            if len(matches) == 1:
                node = matches[0]
        if node is None:
            node = EntityNode(
                uuid=links[person_id] or graph_uuid(f"{group}:person:{person_id}"),
                name=person["name"], group_id=group, labels=["Person"],
            )
        if node.attributes.get("family_person_id") not in (None, int(person_id)):
            raise ValueError("Graphiti 인물이 다른 가족에게 연결되어 있어요.")
        if node.name != person["name"] or node.attributes.get("family_person_id") != int(person_id):
            node.name = person["name"]
            node.attributes["family_person_id"] = int(person_id)
            await graphiti.nodes.entity.save(node)
        mapping[person_id] = node.uuid

    episode_id = graph_uuid(f"{group}:tree:{tree['version']}")
    edges = []
    for viewer in people:
        for target in people:
            relation = find_relationship(tree, viewer["id"], target["id"])
            if relation in ("나", "가족"):
                continue
            edges.append(EntityEdge(
                uuid=graph_uuid(f"{group}:relation:{viewer['id']}:{target['id']}"),
                group_id=group, source_node_uuid=mapping[viewer["id"]],
                target_node_uuid=mapping[target["id"]], name="FAMILY_RELATIONSHIP",
                fact=f"{target['name']}님은 {viewer['name']}님의 {relation}입니다.",
                created_at=now, episodes=[episode_id], attributes={"family_tree": True},
            ))
    episode = EpisodicNode(
        uuid=episode_id, group_id=group, name=f"family_registry_{family_id}_v{tree['version']}",
        source=EpisodeType.text, source_description="SQLite에서 확정된 가족 가계도",
        content="가계도 등록 정보이며 관계가 시작된 시점은 알 수 없습니다.\n"
                + "\n".join([f"등록된 가족: {p['name']}" for p in people] + [e.fact for e in edges]),
        valid_at=now, entity_edges=[e.uuid for e in edges],
    )
    await graphiti.nodes.episode.save(episode)
    for node_uuid in mapping.values():
        await graphiti.edges.episodic.save(EpisodicEdge(
            uuid=graph_uuid(f"{episode_id}:mentions:{node_uuid}"), group_id=group,
            source_node_uuid=episode_id, target_node_uuid=node_uuid, created_at=now,
        ))
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH ()-[r:RELATES_TO {group_id: $group, family_tree: true}]->() "
        "RETURN r.uuid AS uuid, r.fact AS fact", group=group, routing_="r",
    )
    previous = {r["uuid"]: r["fact"] for r in records}
    for edge in edges:
        if previous.get(edge.uuid) != edge.fact:
            await graphiti.edges.entity.save(edge)
    stale = list(previous.keys() - {e.uuid for e in edges})
    if stale:
        await graphiti.edges.entity.delete_by_uuids(stale)
    return mapping
