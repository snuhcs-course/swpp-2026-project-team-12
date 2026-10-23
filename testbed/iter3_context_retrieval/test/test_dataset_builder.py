import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataset_builder import (
    ROOT,
    CompositeCrawler,
    CuratedCrawler,
    build_plan,
    generate,
    make_crawler,
    read_json,
    relationship,
    validate_config,
)


class DatasetBuilderTests(unittest.TestCase):
    def config(self):
        config = read_json(ROOT / "input" / "config.example.json")
        config["download_images"] = False
        return config

    def test_plan_has_multiple_authors_and_day_seven_probes(self):
        config = self.config()
        catalog = read_json(ROOT / "input" / "event_catalog.example.json")
        plan = build_plan(config, validate_config(config, catalog))
        self.assertEqual(len(plan["events"]), config["post_count"])
        for thread_id in config["thread_ids"]:
            events = [event for event in plan["events"] if event["thread_id"] == thread_id]
            self.assertGreaterEqual(len({event["author_username"] for event in events}), 2)
            probe = next(event for event in events if event["kind"] == "probe")
            self.assertEqual(probe["created_at"][:10], "2026-10-11")
            self.assertTrue(probe["evaluation_question"])

    def test_five_member_family_can_use_catalog_templates_through_m5(self):
        config = self.config()
        config["members"].append({
            "username": "test_son", "name": "준호", "gender": "male", "slot": "son",
        })
        config["thread_ids"] = ["lunchbox", "birthday", "knitting"]
        config["post_count"] = 15
        catalog = read_json(ROOT / "input" / "event_catalog.example.json")

        plan = build_plan(config, validate_config(config, catalog))

        self.assertEqual(len(plan["events"]), 15)
        self.assertTrue(all("{" not in event["caption"] for event in plan["events"]))

    def test_fifty_post_week_keeps_all_ten_probes_on_day_seven(self):
        config = self.config()
        config["members"].append({
            "username": "test_son", "name": "준호", "gender": "male", "slot": "son",
        })
        config["thread_ids"] = [
            "basil", "dog", "cafe", "camera", "lunchbox", "bicycle", "birthday", "trip", "knitting", "recital",
        ]
        config["post_count"] = 50
        catalog = read_json(ROOT / "input" / "event_catalog.example.json")

        plan = build_plan(config, validate_config(config, catalog))

        probes = [event for event in plan["events"] if event["kind"] == "probe"]
        self.assertEqual(len(plan["events"]), 50)
        self.assertEqual(len(probes), 10)
        self.assertTrue(all(event["created_at"][:10] == "2026-10-11" for event in probes))

    def test_relationships_match_application_rules(self):
        members = self.config()["members"]
        people = {member["name"]: member for member in members}
        self.assertEqual(relationship(people["지민"], people["도윤"]), "아버지")
        self.assertEqual(relationship(people["선희"], people["도윤"]), "사위")
        self.assertEqual(relationship(people["도윤"], people["지민"]), "딸")

    def test_default_probes_have_required_and_filter_memories_in_history(self):
        config = self.config()
        catalog = read_json(ROOT / "input" / "event_catalog.example.json")
        plan = build_plan(config, validate_config(config, catalog))
        for probe in (event for event in plan["events"] if event["kind"] == "probe"):
            history = [
                event for event in plan["events"]
                if event["thread_id"] == probe["thread_id"] and event["kind"] != "probe"
            ]
            established = {label for event in history for label in event.get("establishes", [])}
            self.assertLessEqual(set(probe["required_memories"]), established)
            self.assertLessEqual(set(probe["must_filter"]), established)

    def test_selected_probe_requires_evaluation_question(self):
        config = self.config()
        catalog = read_json(ROOT / "input" / "event_catalog.example.json")
        probe = next(event for event in catalog["threads"][0]["events"] if event["kind"] == "probe")
        probe.pop("evaluation_question")
        with self.assertRaisesRegex(ValueError, "evaluation_question"):
            validate_config(config, catalog)

    def test_skip_images_writes_manifest(self):
        config = self.config()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            output, plan = generate(config_path, Path(directory) / "out", skip_images=True)
            saved = read_json(output / "manifest.json")
            self.assertEqual(saved["events"], plan["events"])
            self.assertTrue(all(event["image_path"] is None for event in saved["events"]))

    def test_default_crawler_uses_manually_curated_sources(self):
        config = self.config()
        crawler = make_crawler(config)
        self.assertIsInstance(crawler, CompositeCrawler)
        self.assertIsInstance(crawler.crawlers[0], CuratedCrawler)

    def test_curated_sources_cover_default_plan(self):
        config = self.config()
        catalog = read_json(ROOT / "input" / "event_catalog.example.json")
        plan = build_plan(config, validate_config(config, catalog))
        sources = {item["feed_key"] for item in read_json(ROOT / "input" / "curated_sources.example.json")}
        self.assertEqual({event["feed_key"] for event in plan["events"]}, sources)

    def test_image_queries_describe_people_or_human_actions(self):
        catalog = read_json(ROOT / "input" / "event_catalog.example.json")
        human_terms = {"person", "family", "friends", "hands", "adult"}
        for thread in catalog["threads"]:
            for event in thread["events"]:
                words = set(event["image_query"].lower().split())
                self.assertTrue(words & human_terms, event["id"])

    def test_composite_crawler_falls_back_to_next_provider(self):
        calls = []

        class FailingCrawler:
            def download(self, query, destination, feed_key=None):
                calls.append("first")
                raise RuntimeError("no result")

        class SuccessfulCrawler:
            def download(self, query, destination, feed_key=None):
                calls.append("second")
                return {"provider": "fallback"}

        crawler = CompositeCrawler([FailingCrawler(), SuccessfulCrawler()])
        with tempfile.TemporaryDirectory() as directory:
            result = crawler.download("query", Path(directory) / "image.jpg")
        self.assertEqual(result["provider"], "fallback")
        self.assertEqual(calls, ["first", "second"])

    def test_failed_image_refresh_preserves_existing_file(self):
        config = self.config()
        config["download_images"] = True

        class FailingCrawler:
            def download(self, query, destination, feed_key=None):
                destination.write_bytes(b"partial download")
                raise RuntimeError("network failure")

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path = directory / "config.json"
            output = directory / "out"
            image = output / "images" / "01_basil-core.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"existing image")
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

            with patch("dataset_builder.make_crawler", return_value=FailingCrawler()):
                with self.assertRaises(RuntimeError):
                    generate(config_path, output)

            self.assertEqual(image.read_bytes(), b"existing image")
            self.assertFalse(any(output.glob(".images-*")))


if __name__ == "__main__":
    unittest.main()
