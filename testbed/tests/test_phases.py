import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from testbed.common.run_context import (
    PipelineContext,
    default_family_id,
    ensure_seedable_manifest,
    mark_completed,
)
from testbed.pipeline.phases import (
    events_for_seed_phase,
    normalize_phases,
    phase_construct,
    require_dependency,
    seed_events,
)


class PipelineTests(unittest.TestCase):
    def context(self, root, **config):
        path = root / "config.json"
        path.write_text(json.dumps({"dataset_name": "pipeline-test", **config}), encoding="utf-8")
        return PipelineContext.create(path, output=root / "output", backend=root / "backend")

    def test_all_expands_to_safe_phase_order(self):
        self.assertEqual(normalize_phases(["all"]), ["build", "seed-memory", "construct", "seed-probes"])
        with self.assertRaises(ValueError):
            normalize_phases(["construct", "seed-memory"])

    def test_each_dataset_gets_its_own_stable_family_id_unless_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            derived = self.context(root)
            self.assertEqual(derived.family_id, default_family_id("pipeline-test"))
            self.assertGreaterEqual(derived.family_id, 1000)
            self.assertNotEqual(default_family_id("family-week-100-five-members"), default_family_id("example"))
            self.assertEqual(self.context(root, family_id=1).family_id, 1)

    def test_dataset_names_resolve_to_their_config(self):
        context = PipelineContext.create("family-week-100-five-members")
        self.assertEqual(context.config.parent.name, "family-week-100-five-members")
        self.assertEqual(context.output.name, "family-week-100-five-members")

    def test_probe_phase_requires_completed_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(Path(directory))
            mark_completed(context, "build")
            mark_completed(context, "seed-memory")
            with self.assertRaisesRegex(RuntimeError, "construct phase"):
                require_dependency(context, "seed-probes")
            mark_completed(context, "construct")
            require_dependency(context, "seed-probes")

    def test_construction_worker_receives_test_database_and_media_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(Path(directory))
            context.output.mkdir(parents=True, exist_ok=True)
            context.database.touch()
            context.backend.mkdir()
            (context.backend / "manage.py").touch()
            mark_completed(context, "build")
            mark_completed(context, "seed-memory")
            context.database_state.write_text(json.dumps({"family_id": 7}), encoding="utf-8")
            with patch("testbed.pipeline.phases.subprocess.run") as run:
                phase_construct(context)

            environment = run.call_args.kwargs["env"]
            self.assertEqual(environment["DJANGO_DB_PATH"], str(context.database))
            self.assertEqual(environment["DJANGO_MEDIA_ROOT"], str(context.output / "media"))
            self.assertIn("7", run.call_args.args[0])

    def test_seed_phases_split_events_merge_state_and_pin_the_family_id(self):
        seeded_ids = []

        class FakeAdapter:
            def __init__(self, **_):
                pass

            def setup(self):
                pass

            def seed(self, manifest, manifest_path, events, default_password=None, family_id=None):
                seeded_ids.append(family_id)
                return {"family_id": family_id,
                        "post_ids": {event["feed_key"]: index + 10 for index, event in enumerate(events)}}

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            context = self.context(Path(directory), family_id=7)
            context.output.mkdir(parents=True, exist_ok=True)
            manifest = {"events": [
                {"feed_key": "story-core", "kind": "core"},
                {"feed_key": "story-update", "kind": "update"},
                {"feed_key": "story-probe", "kind": "probe"},
            ]}
            context.manifest.write_text(json.dumps(manifest), encoding="utf-8")
            memory = events_for_seed_phase(manifest, "memory")
            probes = events_for_seed_phase(manifest, "probes")
            self.assertEqual([event["feed_key"] for event in memory], ["story-core", "story-update"])
            self.assertEqual([event["feed_key"] for event in probes], ["story-probe"])

            seed_events(context, memory, adapter_class=FakeAdapter)
            seed_events(context, probes, adapter_class=FakeAdapter)
            state = json.loads(context.database_state.read_text(encoding="utf-8"))
            self.assertEqual(state["family_id"], 7)
            self.assertEqual(set(state["post_ids"]), {"story-core", "story-update", "story-probe"})
            self.assertEqual(seeded_ids, [7, 7])

    def test_seed_check_allows_text_only_posts_and_requires_every_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(Path(directory))
            (context.output / "images").mkdir(parents=True)
            (context.output / "images" / "02_box.jpg").write_bytes(b"jpeg")
            manifest = {"events": [
                {"feed_key": "text", "kind": "core", "photos": 0, "image_paths": []},
                {"feed_key": "box", "kind": "core", "photos": 2,
                 "image_path": "images/02_box.jpg", "image_paths": ["images/02_box.jpg", "images/02_box_2.jpg"]},
            ]}
            context.manifest.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "1개"):
                ensure_seedable_manifest(context)
            (context.output / "images" / "02_box_2.jpg").write_bytes(b"jpeg")
            self.assertEqual(ensure_seedable_manifest(context), manifest)

    def test_seed_app_writes_every_event_and_conversation_to_the_app_db(self):
        from testbed.builder.seed_app import seed_app

        calls = {}

        class FakeAdapter:
            def __init__(self, **kwargs):
                calls["init"] = kwargs

            def setup(self):
                pass

            def seed(self, manifest, manifest_path, events, default_password=None, family_id=None):
                calls["events"] = [event["feed_key"] for event in events]
                calls["family_id"] = family_id
                return {"family_id": 3, "post_ids": {"story-core": 1, "story-probe": 2}}

            def seed_conversations(self, manifest, post_ids):
                calls["post_ids"] = post_ids
                return {"comments": 1, "daily_questions": 0}

            def close(self):
                calls["closed"] = True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self.context(root)
            context.output.mkdir(parents=True)
            manifest = {"events": [
                {"feed_key": "story-core", "kind": "core", "photos": 0},
                {"feed_key": "story-probe", "kind": "probe", "photos": 0},
            ]}
            context.manifest.write_text(json.dumps(manifest), encoding="utf-8")
            result = seed_app(context.config, backend=root / "backend", output=context.output,
                              adapter_class=FakeAdapter)

        self.assertEqual(calls["events"], ["story-core", "story-probe"])
        self.assertEqual(calls["post_ids"], {"story-core": 1, "story-probe": 2})
        self.assertEqual(calls["init"]["database"], (root / "backend" / "db.sqlite3").resolve())
        self.assertIsNone(calls["family_id"])  # the app DB keeps its own room IDs
        self.assertTrue(calls["closed"])
        self.assertEqual(result["comments"], 1)


if __name__ == "__main__":
    unittest.main()
