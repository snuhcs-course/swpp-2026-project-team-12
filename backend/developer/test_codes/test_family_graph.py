"""Family identity, provenance and retry regressions; no live AI/Neo4j."""

import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.core.management import call_command
from django.db import transaction
from django.test import TestCase
from graphiti_core.nodes import EntityNode

from apps.accounts.models import User
from apps.accounts.services import update_account
from apps.families.services import create_room
from apps.families.utils.tree import join_tree, tree_data
from apps.posts.models import Post
from integrations.utils.family_graph import sync_family


class FamilyGraphTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="C", display_name="C", gender="male")
        self.room = create_room(self.owner, "family", "password", "21:00")
        self.nodes, self.edges, self.episodes, self.mentions = {}, {}, {}, {}

        def namespace(store):
            async def save(value):
                store[value.uuid] = value
                return value
            return SimpleNamespace(save=AsyncMock(side_effect=save))

        async def query(query, **params):
            if "e:Episodic" in query:
                records = [{"name": e.name} for e in self.episodes.values()]
            elif "MATCH (n:Entity" in query:
                records = [{"uuid": n.uuid} for n in self.nodes.values()
                           if n.group_id == params["group"] and (
                               n.uuid in params["uuids"] or n.name in params["names"]
                               or n.attributes.get("family_person_id") in params["ids"])]
            else:
                records = [{"uuid": e.uuid, "fact": e.fact} for e in self.edges.values()
                           if e.group_id == params["group"] and e.attributes.get("family_tree")]
            return records, None, None

        entity = namespace(self.nodes)
        entity.get_by_uuids = AsyncMock(side_effect=lambda ids: [self.nodes[uid] for uid in ids])
        self.graph = SimpleNamespace(
            build_indices_and_constraints=AsyncMock(),
            driver=SimpleNamespace(execute_query=AsyncMock(side_effect=query)),
            nodes=SimpleNamespace(entity=entity, episode=namespace(self.episodes)),
            edges=SimpleNamespace(entity=namespace(self.edges), episodic=namespace(self.mentions)),
        )

    def join(self, name, anchor):
        user = User.objects.create_user(username=name, display_name=name, gender="male")
        tree = tree_data(self.room)
        join_tree(self.room, user, {
            "tree_version": tree["version"], "person_id": "new_father",
            "additions": [{"id": "new_father", "anchor_id": str(anchor), "relation": "father"}],
        })
        return self.room.members.get(user=user).person

    def sync(self):
        with asyncio.Runner() as runner:
            sync_family(self.graph, self.room.pk, runner)

    def test_join_reuses_existing_person_and_saves_both_directions_with_sources(self):
        child = self.room.members.get(user=self.owner).person
        father = self.join("A", child.pk)
        self.sync()
        grandpa = self.join("B", father.pk)
        existing = EntityNode(name="B", group_id=f"family_{self.room.pk}")
        self.nodes[existing.uuid] = existing
        foreign = EntityNode(name="B", group_id="family_999")
        self.nodes[foreign.uuid] = foreign
        self.sync()
        grandpa.refresh_from_db()
        self.assertEqual(str(grandpa.graphiti_uuid), existing.uuid)
        self.assertNotIn("family_person_id", foreign.attributes)
        self.assertTrue({"B님은 C님의 할아버지입니다.", "C님은 B님의 손자입니다.",
                         "B님은 A님의 아버지입니다.", "A님은 B님의 아들입니다."}
                        <= {e.fact for e in self.edges.values()})
        self.assertEqual(len(self.edges), 6)
        for edge in self.edges.values():
            source = self.episodes[edge.episodes[0]]
            self.assertIn(edge.fact, source.content)
            self.assertIsNone(edge.valid_at)  # Joining does not start a parent/child relationship.
        self.assertEqual(Post.objects.count(), 0)
        calls = self.graph.driver.execute_query.await_count
        self.sync()
        self.assertEqual(self.graph.driver.execute_query.await_count, calls)

    def test_ambiguous_names_are_not_claimed(self):
        for _ in range(2):
            node = EntityNode(name="C", group_id=f"family_{self.room.pk}")
            self.nodes[node.uuid] = node
        self.sync()
        person = self.room.members.get(user=self.owner).person
        self.assertEqual(len(self.nodes), 3)
        self.assertEqual(self.nodes[str(person.graphiti_uuid)].attributes["family_person_id"], person.pk)

    def test_members_with_the_same_name_keep_separate_identities(self):
        father = self.join("A", self.room.members.get(user=self.owner).person_id)
        update_account(father.membership.user, {"name": "C"})
        node = EntityNode(name="C", group_id=f"family_{self.room.pk}")
        self.nodes[node.uuid] = node
        self.sync()
        self.assertEqual(len(self.nodes), 3)
        self.assertEqual(self.room.people.filter(graphiti_uuid__isnull=False).count(), 2)
        self.assertNotIn("family_person_id", node.attributes)

    def test_worker_syncs_a_room_without_posts(self):
        from integrations.ai_workers import graphiti_client
        with patch.object(graphiti_client, "initialize_graphiti", new=AsyncMock(return_value=self.graph)), \
             patch.object(graphiti_client, "close_graphiti", new=AsyncMock()):
            call_command("run_construction_worker", family_id=self.room.pk, once=True, stdout=io.StringIO())
        self.room.refresh_from_db()
        self.assertEqual(self.room.graph_synced_version, self.room.tree_version)
        self.assertEqual(len(self.nodes), 1)

    def test_failure_retries_without_duplicating_nodes_or_marking_done(self):
        self.join("A", self.room.members.get(user=self.owner).person_id)
        save = self.graph.edges.entity.save
        save.side_effect, original = RuntimeError("offline"), save.side_effect
        with self.assertRaises(RuntimeError):
            self.sync()
        node_ids = set(self.nodes)
        self.room.refresh_from_db()
        self.assertEqual(self.room.graph_synced_version, -1)
        self.assertFalse(self.room.people.filter(graphiti_uuid__isnull=False).exists())
        save.side_effect = original
        self.sync()
        self.assertEqual(set(self.nodes), node_ids)
        self.assertEqual(len(self.edges), 2)
        self.room.refresh_from_db()
        self.assertEqual(self.room.graph_synced_version, self.room.tree_version)

    def test_name_edit_updates_same_node_and_relationship_facts(self):
        self.join("A", self.room.members.get(user=self.owner).person_id)
        self.sync()
        node_id = self.room.members.get(user=self.owner).person.graphiti_uuid
        update_account(self.owner, {"name": "새이름"})
        self.sync()
        self.assertEqual(self.nodes[str(node_id)].name, "새이름")
        self.assertEqual(len(self.nodes), 2)
        self.assertTrue(all("새이름" in edge.fact for edge in self.edges.values()))

    def test_rolled_back_join_leaves_no_pending_version(self):
        self.sync()
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.join("A", self.room.members.get(user=self.owner).person_id)
            raise RuntimeError("rollback")
        self.room.refresh_from_db()
        self.assertEqual(self.room.graph_synced_version, self.room.tree_version)
        self.assertEqual(self.room.members.count(), 1)

    def test_join_during_sync_remains_pending(self):
        with asyncio.Runner() as runner:
            def run(coroutine):
                result = runner.run(coroutine)
                self.join("A", self.room.members.get(user=self.owner).person_id)
                return result
            sync_family(self.graph, self.room.pk, SimpleNamespace(run=run))
        self.room.refresh_from_db()
        self.assertLess(self.room.graph_synced_version, self.room.tree_version)
        self.sync()
        self.assertEqual(len(self.nodes), 2)
