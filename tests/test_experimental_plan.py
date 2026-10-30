import argparse
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluate import partition
import experimental_plan as planner
import runtime


class ExperimentalPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.questions, self.gold, self.histories = [], {}, []
        self.serial = 0

        def add(hid, category="single-session-assistant", abstain=False, qid=None):
            if qid is None:
                while True:
                    self.serial += 1
                    qid = f"q_plan_{self.serial}"
                    if partition(qid) == "development":
                        break
            q = {"question_id": qid, "history_id": hid, "question": "What is my color?",
                 "question_date": "2023-05-30"}
            self.questions.append(q)
            self.gold[qid] = {"question_id": qid, "question_type": category,
                              "abstain": abstain, "answer": "blue", "evidence": ["s_" + hid]}
            if not any(h["history_id"] == hid for h in self.histories):
                self.histories.append({"history_id": hid, "sessions": [
                    {"session_id": "s_" + hid, "date": "2023-05-20", "turns": [
                        {"role": "user", "content": "My favorite color is blue."}]}]})
            return q

        add("diagnostic", "single-session-user", qid=planner.DIAGNOSTIC_ID)
        smoke = [add(f"smoke-{i}") for i in range(5)]
        for hid in ("shared-a", "shared-b", "shared-c"):
            add(hid)
            add(hid)
        for category in ("single-session-user", "multi-session", "knowledge-update", "temporal-reasoning"):
            add("single-" + category, category)
        add("single-unanswerable", "single-session-user", abstain=True)
        self.excluded = {planner.DIAGNOSTIC_ID, *(q["question_id"] for q in smoke)}
        self.smoke_path = self.root / "smoke.jsonl"
        planner.write_jsonl(self.root / "questions.jsonl", self.questions)
        planner.write_jsonl(self.root / "histories.jsonl", self.histories)
        planner.write_jsonl(self.root / "gold.jsonl", self.gold.values())
        planner.write_jsonl(self.smoke_path, smoke)
        self.args = argparse.Namespace(data=self.root, smoke=self.smoke_path, out_dir=self.root / "out",
            paired_questions=4, memory_budget=12000, seed=planner.SEED,
            base_url="https://example.test", agent_id="test-plan")

    def test_selection_is_deterministic_and_uses_no_gold_answers(self):
        first = planner.choose_cohort(self.questions, self.gold, self.excluded, 4)
        altered_gold = {qid: {**g, "answer": "an unrelated gold secret", "evidence": ["secret"]}
                        for qid, g in self.gold.items()}
        second = planner.choose_cohort(self.questions, altered_gold, self.excluded, 4)
        self.assertEqual(first, second)
        shared, singles = first
        self.assertEqual((len(shared), len(singles)), (4, 5))
        grouped = {}
        for q in shared:
            grouped.setdefault(q["history_id"], []).append(q)
        self.assertEqual(sorted(map(len, grouped.values())), [2, 2])
        self.assertFalse(self.excluded & {q["question_id"] for q in shared + singles})
        self.assertTrue(all(partition(q["question_id"]) == "development" for q in shared + singles))

    def test_validation_question_excludes_entire_shared_history(self):
        qid = next(f"q_holdout_{i}" for i in range(100) if partition(f"q_holdout_{i}") == "validation")
        questions = self.questions + [{"question_id": qid, "history_id": "shared-a", "question": "Color?"}]
        shared, _ = planner.choose_cohort(questions, self.gold, self.excluded, 4)
        self.assertNotIn("shared-a", {q["history_id"] for q in shared})

    def test_plan_is_offline_with_exact_prepared_counts_and_separate_arm_runs(self):
        with patch.object(runtime, "invoke", side_effect=AssertionError("API invoked")), \
             patch.object(runtime, "run", side_effect=AssertionError("runner invoked")), \
             patch.object(runtime, "main", side_effect=AssertionError("runner main invoked")), \
             patch.object(runtime.official_client, "new_history", side_effect=AssertionError("reset invoked")), \
             patch.object(runtime.official_client, "ask_retrying", side_effect=AssertionError("question invoked")):
            plan = planner.build_plan(self.args)
        self.assertEqual(plan["mode"], "offline-plan-only")
        self.assertFalse(plan["execute"])
        first, second, third = plan["stages"]
        self.assertEqual(first["counts"], {"history_resets": 1, "question_requests": 1,
                                         "preload_requests": 0, "initial_api_operations": 2})
        self.assertEqual(second["counts"]["initial_api_operations"], 10)
        self.assertEqual(third["counts"]["history_resets"], 21)
        self.assertEqual(third["counts"]["question_requests"], 27)
        self.assertEqual(third["counts"]["preload_requests"], 7)
        self.assertEqual(third["counts"]["initial_api_operations"], 55)
        self.assertEqual(plan["total_initial_counts"]["initial_api_operations"], 67)
        self.assertEqual(len({job["fresh_arm_output_directory"] for job in third["jobs"]}), 21)
        for job in third["jobs"]:
            self.assertEqual(len(job["history_ids"]), 1)
            self.assertFalse(job["execute"])
            self.assertNotIn("--execute", job["command_argv"])
            manifest = json.loads(Path(job["runtime_manifest"]).read_text())
            self.assertEqual(manifest["question_ids"], job["question_ids"])
            self.assertEqual(job["counts"]["preload_requests"],
                             sum(map(len, manifest["memory_parts"].values())))
            self.assertIn("source_sha256", manifest)
        orders = [row["arm_order"] for row in third["schedule"][:6]]
        self.assertEqual(len({tuple(order) for order in orders}), 6)
        # Gold files are kept only for reporting; source inputs remain ordinary
        # public question/history files, and no generated memory contains gold.
        self.assertEqual(first["jobs"][0]["question_ids"], [planner.DIAGNOSTIC_ID])
        comparison = plan["compare_command_argv"]
        self.assertEqual(comparison.count("--arm"), 21)
        names = [comparison[i + 1].split("=", 1)[0] for i, value in enumerate(comparison) if value == "--arm"]
        self.assertEqual(names[:7], ["bm25-4"] * 7)
        self.assertEqual(names[7:14], ["calibrated-4"] * 7)
        self.assertEqual(names[14:], ["calibrated-memory"] * 7)

    def test_existing_artifacts_are_refused_before_any_write(self):
        self.args.out_dir.mkdir()
        sentinel = self.args.out_dir / "frozen-plan.json"
        sentinel.write_text("immutable")
        with patch.object(runtime, "prepare", side_effect=AssertionError("must refuse before preparation")):
            with self.assertRaisesRegex(ValueError, "preserve the frozen plan"):
                planner.build_plan(self.args)
        self.assertEqual(sentinel.read_text(), "immutable")
        self.assertEqual(list(self.args.out_dir.iterdir()), [sentinel])

    def test_cli_rejects_execute_flag(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
            planner.main(["--out-dir", str(self.root / "unsafe"), "--execute"])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse((self.root / "unsafe").exists())


if __name__ == "__main__":
    unittest.main()
