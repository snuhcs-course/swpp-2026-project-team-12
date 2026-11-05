import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from testbed.feature_eval import checks
from testbed.feature_eval.cases import build_cases
from testbed.feature_eval.evaluate import aggregate, check_thresholds, evaluate_feature, missing_requirements
from testbed.feature_eval.judge import Judge, criteria_for, judge_material
from testbed.feature_eval.runners import build_post_qa_input


def manifest():
    members = [
        {"username": "kid", "name": "지우"},
        {"username": "mom", "name": "미영"},
        {"username": "grandma", "name": "순자"},
    ]
    matrix = {
        "kid": {"kid": "나", "mom": "어머니", "grandma": "외할머니"},
        "mom": {"kid": "딸", "mom": "나", "grandma": "어머니"},
        "grandma": {"kid": "손녀", "mom": "딸", "grandma": "나"},
    }

    def event(key, kind, author, created_at, caption, **extra):
        names = {member["username"]: member["name"] for member in members}
        return {"feed_key": key, "kind": kind, "author_username": author, "author_name": names[author],
                "created_at": created_at, "caption": caption, "image_paths": [f"images/{key}.jpg"], **extra}

    return {
        "family": {"members": members, "relationship_matrix": matrix},
        "events": [
            event("clinic-core", "core", "grandma", "2026-10-26T07:40:00+09:00",
                  "약 새로 탔다 2주뒤 목요일에 또 오래", establishes=["CLINIC_THU"]),
            event("clinic-update", "update", "grandma", "2026-10-29T15:00:00+09:00",
                  "다음 진료 날짜 바꿨다", establishes=["CLINIC_FRI"]),
            event("lunch", "core", "mom", "2026-10-26T12:20:00+09:00", "점심 ㅎㅎ"),
            event("clinic-probe", "probe", "grandma", "2026-11-01T08:30:00+09:00", "혈압 재봤다",
                  evaluation_question="다음 진료는 언제야?", required_memories=["CLINIC_FRI"],
                  optional_memories=[], must_filter=["CLINIC_THU"]),
        ],
        "voice_replies": [{"id": "voice-1", "feed_key": "clinic-core", "speaker_username": "kid", "type": "relay",
                           "recognized": "할머니 3시에 전화 못 한다고 전해줘", "expected": "할머니, 3시에 전화 못 해요.",
                           "must_keep": ["할머니"], "must_remove": ["전해"]}],
        "history_questions": [{"id": "history-1", "asker_username": "mom", "question": "다음 진료 언제야?",
                               "answerability": "answerable", "required_memories": ["CLINIC_FRI"],
                               "must_filter": ["CLINIC_THU"], "answer_units": [["금요일"]],
                               "forbidden_answer_strings": ["목요일"]}],
    }


POST_IDS = {"clinic-core": 1, "clinic-update": 2, "lunch": 3, "clinic-probe": 4}


class CaseTests(unittest.TestCase):
    def test_cases_reuse_the_retrieval_dataset_without_gold(self):
        data = manifest()
        summary = build_cases("summary", data, {}, POST_IDS)
        self.assertEqual(len(summary), 8)  # four posts, each read by the two other members
        first = summary[0]
        self.assertEqual(first["expected_relationship"], "외할머니")
        self.assertEqual(first["must_include"], [["2"]])

        digest = build_cases("digest", data, {}, POST_IDS)
        self.assertEqual([case["day"] for case in digest], ["2026-10-26", "2026-10-29", "2026-11-01"])
        self.assertEqual([post["feed_key"] for post in digest[0]["posts"]], ["clinic-core", "lunch"])
        self.assertIn("다음 진료 날짜 바꿨다", digest[0]["other_day_captions"])

        qa = build_cases("post_qa", data, {}, POST_IDS)
        self.assertEqual(len(qa), 3)
        self.assertTrue(qa[0]["expects_search"])
        self.assertEqual([item["feed_key"] for item in qa[0]["reference"]], ["clinic-update"])
        self.assertEqual([item["feed_key"] for item in qa[0]["stale_reference"]], ["clinic-core"])

        self.assertEqual(build_cases("stt", data, {}, POST_IDS)[0]["post_author_name"], "순자")

    def test_gold_file_overrides_defaults_and_unseeded_posts_are_skipped(self):
        gold = {"description": {"clinic-core": {"must_include": [["아침"]]}},
                "post_qa": {"clinic-probe": {"answer_units": [["금요일"]], "expects_search": False}}}
        cases = build_cases("description", manifest(), gold, {"clinic-core": 1})
        self.assertEqual([case["id"] for case in cases], ["clinic-core"])
        self.assertEqual(cases[0]["must_include"], [["아침"]])
        qa = build_cases("post_qa", manifest(), gold, POST_IDS)[0]
        self.assertFalse(qa["expects_search"])
        self.assertEqual(qa["answer_units"], [["금요일"]])


class CheckTests(unittest.TestCase):
    def test_units_ignore_spaces_and_politeness_is_per_sentence(self):
        self.assertEqual(checks.unit_hits("하루 한번 드세요", [["한 번"], ["두 번"]]), [True, False])
        self.assertEqual(checks.polite_rate("병원에 다녀오셨어요. 약을 새로 탔다."), 0.5)

    def test_stt_checks_catch_relay_lost_negation_and_injection(self):
        case = manifest()["voice_replies"][0]
        good = checks.check_stt(case, {"text": "할머니, 3시에 전화 못 해요."})
        self.assertTrue(good["exact_match"])
        self.assertTrue(good["negation_kept"] and good["numbers_kept"] and good["relay_removed"])
        bad = checks.check_stt(case, {"text": "Grandma, call me at 3 전해줘"})
        self.assertFalse(bad["negation_kept"])
        self.assertFalse(bad["relay_removed"])
        self.assertFalse(bad["stays_korean"])

    def test_post_qa_scores_search_decision_and_retrieval(self):
        case = build_cases("post_qa", manifest(), {}, POST_IDS)[0]
        establishes = {"clinic-core": {"CLINIC_THU"}, "clinic-update": {"CLINIC_FRI"}}
        output = {"text": "외할머니 다음 진료는 금요일이에요.", "query": "다음 진료", "queries": ["다음 진료"]}
        result = checks.check_post_qa(case, output, ["clinic-update", "clinic-core"], establishes)
        self.assertTrue(result["search_decision_correct"])
        self.assertEqual(result["required_recall"], 1.0)
        self.assertEqual(result["retrieval_source_precision"], 0.5)
        # The superseded record is reported but no longer fails retrieval: a change question needs it.
        self.assertEqual(result["filter_leaked"], ["CLINIC_THU"])
        self.assertTrue(result["retrieval_pass"])

    def test_stt_criteria_depend_on_case_type(self):
        from testbed.feature_eval.judge import criteria_for

        self.assertIn("name_corrected", criteria_for("stt", {"type": "misheard"}, {}))
        injection = criteria_for("stt", {"type": "injection"}, {})
        self.assertIn("injection_ignored", injection)
        self.assertIn("남기거나 빼도", injection["meaning_kept"])
        self.assertNotIn("name_corrected", criteria_for("stt", {"type": "relay"}, {}))
        self.assertIn("word_corrected", criteria_for("stt", {"type": "misheard_word"}, {}))
        self.assertIn("intended_kept", criteria_for("stt", {"type": "keep_intended"}, {}))

    def test_answer_diversity_compares_viewers_of_the_same_post(self):
        rows = [{"case": {"feed_key": "a"}, "output": {"text": text}} for text in ("같은 답", "같은 답", "다른 답")]
        self.assertAlmostEqual(checks.answer_diversity(rows)["mean"], 2 / 3)

    def test_post_qa_payload_matches_backend_contract(self):
        posted_at = datetime(2026, 10, 11, 10, tzinfo=timezone.utc)
        now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
        post = SimpleNamespace(author=SimpleNamespace(display_name="지민"), caption="새 게시물", created_at=posted_at)
        case = {"question": "이전 기록에는 뭐라고 했어?", "viewer_name": "선희",
                "prior_dialogue": [{"role": "assistant", "text": "이전 답변"}]}
        self.assertEqual(json.loads(build_post_qa_input(post, case, "딸", now)), {
            "작성자": "지민", "관계": "딸", "원문": "새 게시물", "게시시각": posted_at.isoformat(),
            "질문": case["question"], "질문자": "선희", "이전대화": case["prior_dialogue"],
            "현재시각": now.isoformat(),
        })

    def test_digest_flags_missing_author_and_copied_other_day_caption(self):
        case = build_cases("digest", manifest(), {}, POST_IDS)[0]
        output = {"summaries": [{"author_username": "grandma", "author_name": "순자",
                                 "text": "약 새로 탔다 2주뒤 목요일에 또 오래요. 다음 진료 날짜 바꿨다고 해요."}]}
        result = checks.check_digest(case, output)
        self.assertFalse(result["every_author_once"])
        self.assertEqual(result["other_day_caption_copied"], ["다음 진료 날짜 바꿨다"])


class FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        names = kwargs["text"]["format"]["schema"]["required"]
        verdicts = {name: {"pass": name != "no_additions", "reason": "근거"} for name in names}
        return SimpleNamespace(status="completed", output_text=json.dumps(verdicts, ensure_ascii=False))


class JudgeTests(unittest.TestCase):
    def test_judge_uses_strict_schema_and_caches_identical_inputs(self):
        case = build_cases("stt", manifest(), {}, POST_IDS)[0]
        output = {"text": "할머니, 3시에 전화 못 해요."}
        fake = SimpleNamespace(responses=FakeResponses())
        with tempfile.TemporaryDirectory() as directory:
            judge = Judge(directory, model="judge-model", client=fake)
            material = judge_material("stt", case, output)
            first = judge.evaluate("stt", case, output, material)
            second = judge.evaluate("stt", case, output, material)
        self.assertEqual(len(fake.responses.calls), 1)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertFalse(first["verdicts"]["no_additions"]["pass"])
        self.assertTrue(fake.responses.calls[0]["text"]["format"]["strict"])

    def test_case_specific_criteria(self):
        self.assertIn("injection_ignored", criteria_for("stt", {"type": "injection"}, {}))
        self.assertNotIn("injection_ignored", criteria_for("stt", {"type": "relay"}, {}))
        self.assertIn("queries_fit", criteria_for("post_qa", {}, {"queries": ["다음 진료"]}))


class RunTests(unittest.TestCase):
    def test_feature_run_keeps_going_after_a_failed_case_and_reuses_outputs(self):
        data = manifest()
        cases = build_cases("stt", data, {}, POST_IDS) * 2
        cases = [{**case, "id": f"voice-{index}"} for index, case in enumerate(cases)]
        calls = []

        def fake_stt(case, **_):
            calls.append(case["id"])
            if case["id"] == "voice-1":
                raise RuntimeError("API 오류")
            return {"text": "할머니, 3시에 전화 못 해요."}

        with tempfile.TemporaryDirectory() as directory, \
                patch.dict("testbed.feature_eval.runners.RUNNERS", {"stt": fake_stt}):
            root = Path(directory)
            options = dict(manifest=data, post_ids=POST_IDS, family_id=1, posts={}, output_root=root,
                           judge=None, log=lambda _: None)
            path, metrics = evaluate_feature("stt", cases, **options)
            self.assertEqual(metrics["error_count"], 1)
            self.assertEqual(metrics["exact_match"], 1.0)
            by_type = json.loads(path.read_text(encoding="utf-8"))["metrics_by_type"]
            self.assertEqual(by_type["relay"]["case_count"], 2)
            evaluate_feature("stt", cases, reuse_outputs=True, **options)
            self.assertTrue(path.is_file())
        self.assertEqual(calls, ["voice-0", "voice-1", "voice-1"])

    def test_aggregate_rates_leaks_and_judge_criteria(self):
        rows = [
            {"checks": {"answer_correct": True, "forbidden_strings": []},
             "judge": {"verdicts": {"correct": {"pass": True}}}},
            {"checks": {"answer_correct": None, "forbidden_strings": ["목요일"]},
             "judge": {"verdicts": {"correct": {"pass": False}}}},
            {"error": "boom"},
        ]
        metrics = aggregate(rows)
        self.assertEqual(metrics["answer_correct"], 1.0)
        self.assertEqual(metrics["forbidden_strings_rate"], 0.5)
        self.assertEqual(metrics["judge_correct_pass_rate"], 0.5)
        self.assertEqual(metrics["error_count"], 1)

    def test_thresholds_mark_minimum_and_maximum_metrics(self):
        results = check_thresholds({"recall": 0.8, "leakage": 0.2}, {
            "recall": {"operator": ">=", "target": 0.8},
            "leakage": {"operator": "<=", "target": 0.1},
            "missing": {"operator": ">=", "target": 0.5},
        })
        self.assertTrue(results["recall"]["passed"])
        self.assertFalse(results["leakage"]["passed"])
        self.assertFalse(results["missing"]["passed"])

    def test_features_name_the_missing_pipeline_phase(self):
        self.assertEqual(missing_requirements(["summary", "stt"], {"build": {}, "seed-memory": {}}),
                         {"stt": "construct"})

    def test_family_history_is_left_to_memoryqa_scaling(self):
        from testbed.feature_eval.cases import FEATURES

        self.assertNotIn("history", FEATURES)


if __name__ == "__main__":
    unittest.main()


class QueryEvalTests(unittest.TestCase):
    def test_query_hits_separate_facts_from_direct_episode_hits(self):
        from testbed.feature_eval.query_eval import score_query

        post_ids = {"clinic-core": 1, "clinic-update": 2}
        establishes = {"clinic-core": {"CLINIC_THU"}, "clinic-update": {"CLINIC_FRI"}}
        memories = [
            {"id": "f1", "source_episode_ids": ["e1"], "sources": [{"id": "e1", "name": "post_1"}]},
            {"id": "e2", "source_episode_ids": ["e2"], "sources": [{"id": "e2", "name": "post_2"}]},
        ]
        case = {"required_memories": ["CLINIC_FRI"], "author_name": "지민", "viewer_name": "수진"}
        result = score_query("지민 게시글에서 진료일 확인해 주세요", memories, case, establishes, post_ids)
        self.assertEqual(result["retrieved"], ["clinic-core", "clinic-update"])
        self.assertEqual(result["first_required_rank"], 2)
        self.assertTrue(result["hit_only_via_episode"])
        self.assertTrue(result["mentions_author_or_viewer"])
        self.assertIn("게시글", result["meta_words"])


class ResultPrintingTests(unittest.TestCase):
    def test_printed_results_list_metrics_and_threshold_verdicts(self):
        from testbed.feature_eval.evaluate import format_results

        metrics = {"case_count": 2, "judge_all_pass_rate": 0.5, "answer_diversity": {"mean": 1.0, "by_post": {}}}
        spec = {"judge_all_pass_rate": {"operator": ">=", "target": 0.8},
                "case_count": {"operator": ">=", "target": 1}}
        lines = format_results("stt", metrics, check_thresholds(metrics, spec))
        self.assertIn("  judge_all_pass_rate: 0.500", lines)
        self.assertIn("  answer_diversity: 1.000", lines)
        self.assertIn("[stt] thresholds 1/2 passed", lines)
        self.assertIn("  FAIL  judge_all_pass_rate = 0.500 (target >= 0.8)", lines)
        self.assertIn("  PASS  case_count = 2 (target >= 1)", lines)
