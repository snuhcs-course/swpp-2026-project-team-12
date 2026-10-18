import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from adapters.talkdock_django import build_post_qa_input
from pipeline import (
    PipelineContext,
    evaluate_cases,
    events_for_seed_phase,
    mark_completed,
    normalize_phases,
    require_dependency,
    seed_events,
)


class PipelineTests(unittest.TestCase):
    def context(self, root):
        config = root / "config.json"
        config.write_text(json.dumps({"dataset_name": "pipeline-test"}), encoding="utf-8")
        return PipelineContext.create(config, output=root / "output", backend=root / "backend")

    def test_all_expands_to_safe_phase_order(self):
        self.assertEqual(
            normalize_phases(["all"]),
            ["build", "seed-memory", "construct", "seed-probes", "evaluate"],
        )
        with self.assertRaises(ValueError):
            normalize_phases(["construct", "seed-memory"])

    def test_post_qa_payload_matches_backend_contract(self):
        posted_at = datetime(2026, 10, 11, 10, tzinfo=timezone.utc)
        current_time = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
        post = SimpleNamespace(
            author=SimpleNamespace(display_name="지민"),
            caption="새 게시물",
            created_at=posted_at,
        )
        event = {
            "evaluation_question": "이전 기록에는 뭐라고 했어?",
            "prior_dialogue": [{"role": "assistant", "text": "이전 답변"}],
        }
        payload = json.loads(build_post_qa_input(
            post, event, "딸", {"name": "선희"}, current_time,
        ))
        self.assertEqual(payload, {
            "작성자": "지민",
            "관계": "딸",
            "원문": "새 게시물",
            "게시시각": posted_at.isoformat(),
            "질문": event["evaluation_question"],
            "질문자": "선희",
            "이전대화": event["prior_dialogue"],
            "현재시각": current_time.isoformat(),
        })

    def test_probe_phase_requires_completed_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(Path(directory))
            mark_completed(context, "build")
            mark_completed(context, "seed-memory")
            with self.assertRaisesRegex(RuntimeError, "construct phase"):
                require_dependency(context, "seed-probes")
            mark_completed(context, "construct")
            require_dependency(context, "seed-probes")

    def test_seed_phases_split_events_and_merge_database_state(self):
        class FakeAdapter:
            def __init__(self, **_):
                self.closed = False

            def setup(self):
                pass

            def seed(self, manifest, manifest_path, events, default_password=None):
                return {
                    "family_id": 7,
                    "post_ids": {event["feed_key"]: index + 10 for index, event in enumerate(events)},
                }

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as directory:
            context = self.context(Path(directory))
            context.output.mkdir(parents=True, exist_ok=True)
            manifest = {
                "events": [
                    {"feed_key": "story-core", "kind": "core"},
                    {"feed_key": "story-update", "kind": "update"},
                    {"feed_key": "story-probe", "kind": "probe"},
                ]
            }
            context.manifest.write_text(json.dumps(manifest), encoding="utf-8")
            memory = events_for_seed_phase(manifest, "memory")
            probes = events_for_seed_phase(manifest, "probes")
            self.assertEqual([event["feed_key"] for event in memory], ["story-core", "story-update"])
            self.assertEqual([event["feed_key"] for event in probes], ["story-probe"])

            seed_events(context, memory, adapter_class=FakeAdapter)
            seed_events(context, probes, adapter_class=FakeAdapter)
            state = json.loads((context.output / "database_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["family_id"], 7)
            self.assertEqual(set(state["post_ids"]), {"story-core", "story-update", "story-probe"})

    def test_evaluation_maps_graph_sources_to_manifest_labels(self):
        manifest = {
            "events": [
                {"feed_key": "story-core", "establishes": ["STORY_CURRENT"]},
                {"feed_key": "story-old", "establishes": ["STORY_OLD"]},
                {
                    "feed_key": "story-probe",
                    "kind": "probe",
                    "required_memories": ["STORY_CURRENT"],
                    "optional_memories": [],
                    "must_filter": ["STORY_OLD"],
                },
            ]
        }
        database_state = {
            "post_ids": {"story-core": 10, "story-old": 11, "story-probe": 12}
        }
        cases = [{
            "feed_key": "story-probe",
            "expected_relationship": "딸",
            "answer": "딸이 남긴 새 소식이에요.",
            "query": "최근 이야기",
            "memories": [{"sources": [{"name": "post_10"}, {"name": "post_11"}]}],
        }]

        evaluated, metrics = evaluate_cases(manifest, database_state, cases)
        self.assertEqual(evaluated[0]["required_found"], ["STORY_CURRENT"])
        self.assertEqual(evaluated[0]["forbidden_retrieved"], ["STORY_OLD"])
        self.assertEqual(metrics["mean_required_recall"], 1.0)
        self.assertEqual(metrics["filter_leakage_case_rate"], 1.0)
        self.assertEqual(metrics["mean_retrieval_source_precision"], 0.5)


if __name__ == "__main__":
    unittest.main()
