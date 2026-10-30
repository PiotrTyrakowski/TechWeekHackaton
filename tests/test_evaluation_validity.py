import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import evaluation_diagnostics as d
import evaluation_gates as gates
from official import score


def encoded(rows):
    return "".join(json.dumps(r) + "\n" for r in rows).encode()


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.q = [{"question_id": "q1", "history_id": "user", "question": "Cat?", "question_date": "2023-05-30"},
                  {"question_id": "q2", "history_id": "user", "question": "Unknown?", "question_date": "2023-05-30"}]
        self.gold = [{"question_id": "q1", "question_type": "single-session-user", "abstain": False, "answer": "Luna", "evidence": ["s1"]},
                     {"question_id": "q2", "question_type": "single-session-user", "abstain": True, "answer": "", "evidence": []}]
        self.evidence = [{"id": "s1", "date": "2023-05-29", "text": "user: My cat is Luna"}]
        self.raw = {"question_id": "q1", "status": "answered", "history_id": "remote-A", "answer": "Luna [E1]",
                    "abstained": False, "citations": [{"label": "E1", "id": "s1", "date": "2023-05-29"}], "unknown_citations": [], "latency_s": 1.5}
        # Use the real parser's exact citation schema, including date metadata.
        self.raw["citations"], _ = d.parse_citations(self.raw["answer"], self.evidence)
        self.pred = {"question_id": "q1", "abstain": False, "answer": "Luna", "citations": ["s1"]}
        self.attempts = [{"operation": "new_history", "dataset_history": "user", "exit_code": 0, "wall_s": .5,
                          "result": {"status": "history", "history_id": "remote-A"}},
                         {"operation": "question", "dataset_history": "user", "question_id": "q1", "exit_code": 0, "wall_s": 2, "result": self.raw},
                         {"operation": "question", "dataset_history": "user", "question_id": "q2", "exit_code": 4, "wall_s": 3,
                          "result": {"status": "refused", "code": "previous_pending", "retries": 2, "history_id": "remote-A"}}]
        self.files = {"predictions.jsonl": encoded([self.pred]), "results.jsonl": encoded([self.raw]),
                      "attempts.jsonl": encoded(self.attempts),
                      "evidence/" + d.sha(b"q1") + ".json": json.dumps(self.evidence).encode()}

    def report(self):
        return d.build_report(self.files, self.q, self.gold)

    def test_real_scorer_completion_and_transport_failures_stay_separate(self):
        report = self.report()
        self.assertEqual(report["scope"]["response_completion_rate"], .5)
        self.assertEqual(report["actual_prediction_outcomes_local"]["wrong"], 0)
        self.assertEqual(report["actual_prediction_outcomes_local"]["correct"], 1)
        self.assertEqual(report["operations"]["observed_api_operations"], 5)
        expected = score.summarize([score.score_question(self.pred, self.gold[0]), score.score_question(None, self.gold[1])])
        self.assertEqual(report["full_scope_official_submission"], expected)
        self.assertIsNone(report["completed_only_official_local"]["all"]["abstention_recall"])
        self.assertEqual(report["per_question"][0]["prediction_provenance"], "verified")

    def test_paraphrase_is_unjudged_not_wrong(self):
        self.pred["answer"] = "The pet is named after the moon"
        self.files["predictions.jsonl"] = encoded([self.pred])
        report = self.report()
        self.assertEqual(report["actual_prediction_outcomes_local"]["unjudged"], 1)
        self.assertEqual(report["actual_prediction_outcomes_local"]["wrong"], 0)
        self.assertFalse(report["official_llm_judge_run"])

    def test_false_abstention_still_has_zero_official_evidence_f1(self):
        self.files["predictions.jsonl"] = encoded([{**self.pred, "abstain": True, "answer": "", "citations": []}])
        report = self.report()
        self.assertEqual(report["completed_only_official_local"]["all"]["false_abstention"], 1)
        self.assertEqual(report["completed_only_official_local"]["all"]["evidence_f1"], 0)

    def test_actual_abstention_recall_and_unjudged_counts(self):
        p = {"question_id": "q2", "abstain": True, "answer": "", "citations": []}
        self.files["predictions.jsonl"] = encoded([self.pred, p])
        self.assertEqual(self.report()["completed_only_official_local"]["all"]["abstention_recall"], 1)

    def test_invalid_citation_count_includes_rejected_attempt_without_prediction(self):
        invalid = {**self.raw, "question_id": "q2", "answer": "Blue [E99]", "unknown_citations": ["E99"]}
        self.attempts[-1]["result"] = invalid
        self.attempts[-1]["exit_code"] = 0
        self.files["attempts.jsonl"] = encoded(self.attempts)
        report = self.report()
        self.assertEqual(report["citations"]["invalid_question_n"], 1)
        self.assertEqual(report["scope"]["raw_responses_completed"], 2)
        self.assertEqual(report["scope"]["valid_predictions"], 1)

    def test_wrong_current_mapping_detected_even_if_session_is_in_history(self):
        self.raw["citations"][0]["id"] = "s_other"
        self.files["results.jsonl"] = encoded([self.raw])
        report = self.report()
        self.assertIn("final_segment_mapping_mismatch", report["per_question"][0]["invalid_citation_reasons"])

    def test_missing_original_evidence_does_not_claim_valid_citations(self):
        del self.files["evidence/" + d.sha(b"q1") + ".json"]
        self.assertIsNone(self.report()["citations"]["invalid_question_rate"])
        self.assertEqual(self.report()["citations"]["unverifiable_question_n"], 1)

    def test_duplicate_and_unknown_ids_rejected(self):
        self.files["predictions.jsonl"] = encoded([self.pred, self.pred])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.report()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            d.build_report({}, self.q + [self.q[0]], self.gold)

    def test_uncertain_pending_operation_not_fabricated_as_exact_api_count(self):
        self.files["checkpoint.json"] = json.dumps({"pending": {"request_id": "lost", "operation": "question"}}).encode()
        self.assertTrue(self.report()["operations"]["unlogged_pending_operation_possible"])

    def test_compare_requires_same_dates_and_detects_reused_remote_history(self):
        a = self.report()
        b = copy.deepcopy(a)
        report = d.compare({"a": a, "b": b})
        self.assertIn("Reactor history reused between configurations", report["validity_issues"])
        self.assertEqual(report["paired_actual_citation_f1_delta"], 0)
        b["per_question"][0]["question_record"]["question_date"] = "2024-01-01"
        with self.assertRaisesRegex(ValueError, "date"):
            d.compare({"a": a, "b": b})

    def test_snapshot_includes_original_evidence_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "evidence").mkdir()
            (root / "evidence/x.memory.json").write_text('["dated memory"]')
            self.assertIn("evidence/x.memory.json", d.load_snapshot(root))
            d.write_new(root / "frozen.json", {})
            with self.assertRaises(FileExistsError):
                d.write_new(root / "frozen.json", {"changed": True})

    def test_final_coverage_is_gold_free_and_requires_all_146(self):
        report = d.coverage(self.q, [self.pred])
        self.assertFalse(report["submission_ready"])
        self.assertEqual(report["per_history_progress"]["user"]["completed"], 1)
        self.assertIn("Expected 146 questions, found 2", report["format_errors"])
        predictions = [self.pred, {"question_id": "q2", "abstain": True, "answer": "", "citations": []}]
        self.assertTrue(d.coverage(self.q, predictions, expected=2)["submission_ready"])
        self.assertFalse(d.coverage(self.q, predictions + [self.pred], expected=2)["submission_ready"])


class GateSelectionTests(unittest.TestCase):
    def fixture(self):
        questions, gold = [], {}
        serial = 0
        def add(hid, category, abstain=False, fixed=None):
            nonlocal serial
            while True:
                serial += 1
                qid = fixed or f"q_eval_{serial}"
                if fixed or d.partition(qid) == "development":
                    break
            q = {"question_id": qid, "history_id": hid, "question": "Color?", "question_date": "2023-05-30"}
            questions.append(q)
            gold[qid] = {"question_id": qid, "question_type": category, "abstain": abstain, "answer": "secret", "evidence": ["secret"]}
        for qid in gates.DIAGNOSTICS:
            add(qid, "single-session-user", fixed=qid)
        for category in gates.STRATA:
            for i in range(5):
                add(f"{category}{i}", category, category == "unanswerable")
        for i in range(3):
            add("paired" + str(i), "single-session-assistant")
            add("paired" + str(i), "single-session-assistant")
        return questions, gold

    def test_frozen_selection_ignores_gold_answer_and_evidence(self):
        q, g = self.fixture()
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            first = gates.select(q, g)
            altered = {k: {**v, "answer": "different", "evidence": []} for k, v in g.items()}
            self.assertEqual(first, gates.select(q, altered))
        self.assertEqual(list(map(len, first)), [2, 6, 4, 8])
        self.assertEqual(len({r["history_id"] for r in first[2]}), 2)
        all_ids = [r["question_id"] for cohort in first for r in cohort]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_history_with_validation_question_excluded_from_all_new_cohorts(self):
        q, g = self.fixture()
        heldout_id = next(f"q_v{i}" for i in range(100) if d.partition(f"q_v{i}") == "validation")
        q.append({"question_id": heldout_id, "history_id": "paired0"})
        self.assertNotIn("paired0", {r["history_id"] for cohort in gates.select(q, g)[1:] for r in cohort})

    def test_prepared_counts_and_prefix_payloads_with_network_disabled(self):
        q, g = self.fixture()
        histories = [{"history_id": hid, "sessions": [{"session_id": "s_" + hid, "date": "2023-05-29",
                      "turns": [{"role": "user", "content": "My favorite color is blue."}]}]}
                     for hid in {r["history_id"] for r in q}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "questions.jsonl").write_bytes(encoded(q))
            (root / "gold.jsonl").write_bytes(encoded(list(g.values())))
            (root / "histories.jsonl").write_bytes(encoded(histories))
            with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
                 patch.object(gates, "prepare_memory", wraps=gates.prepare_memory) as memory:
                plan = gates.build(root, root / "frozen")
            self.assertEqual([r["initial_operations"]["total"] for r in plan["gates"]], [4, 24, 14, 32])
            self.assertEqual(plan["initial_operations_total_without_optional_controls"], 74)
            self.assertTrue(all(len(call.args[1]) == 1 for call in memory.call_args_list))
            for path in (root / "frozen").rglob("*prefix-memory.json"):
                self.assertNotIn("secret", path.read_text())
            with self.assertRaisesRegex(ValueError, "fresh output"):
                gates.build(root, root / "frozen")


if __name__ == "__main__":
    unittest.main()
