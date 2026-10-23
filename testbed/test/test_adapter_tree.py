import importlib.util
import tempfile
import unittest
from pathlib import Path

from adapters.talkdock_django import TalkDockDjangoAdapter
from dataset_builder import ROOT, build_plan, read_json, validate_config


@unittest.skipUnless(importlib.util.find_spec("django"), "Django is required for database seeding")
class TreeSeedTests(unittest.TestCase):
    def test_tree_seeding_is_idempotent_and_uses_the_application_relationship_search(self):
        config = read_json(ROOT / "input/config.example.json")
        config["download_images"] = False
        manifest = build_plan(config, validate_config(config, read_json(ROOT / "input/event_catalog.example.json")))
        with tempfile.TemporaryDirectory() as folder:
            adapter = TalkDockDjangoAdapter(ROOT.parent / "backend", Path(folder) / "test.sqlite3", Path(folder) / "media")
            adapter.setup()
            try:
                first = adapter.seed(manifest, Path(folder) / "manifest.json", [])
                second = adapter.seed(manifest, Path(folder) / "manifest.json", [])
                self.assertEqual(first, second)
                self.assertEqual(adapter.models["membership"].objects.count(), 4)
                self.assertEqual(adapter.models["person"].objects.count(), 4)
                self.assertEqual(adapter.models["parent_child"].objects.count(), 3)
                self.assertEqual(adapter.models["partnership"].objects.count(), 1)
                room = adapter.models["family"].objects.get(pk=first["family_id"])
                self.assertEqual(room.tree_version, 1)
                from apps.families.utils import relationship
                users = adapter.models["user"].objects
                self.assertEqual(relationship(users.get(username="test_sunhee"),
                                              users.get(username="test_doyun"), room), "딸의 배우자")
            finally:
                adapter.close()
