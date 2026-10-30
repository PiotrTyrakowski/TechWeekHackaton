import copy
import unittest
from unittest.mock import patch

from evaluate_attribution import evaluate_policy


class AttributionEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.questions = [{"question_id": "q1", "history_id": "h1", "question": "Cat name?", "question_date": "2023-05-30"},
                          {"question_id": "q2", "history_id": "h2", "question": "Missing?", "question_date": "2023-05-30"}]
        self.gold = [{"question_id": qid, "question_type": "single-session-user", "answer": "Luna",
                      "abstain": False, "evidence": ["s1"]} for qid in ("q1", "q2")]
        self.history = {"history_id": "h1", "sessions": [{"session_id": "s1", "date": "2023-05-29",
                        "turns": [{"role": "user", "content": "My cat is Luna."}]}]}
        self.evidence = {"q1": [{"id": "s1", "date": "2023-05-29", "text": "user: My cat is Luna."}]}
        self.results = [{"question_id": "q1", "status": "answered", "answer": "Luna", "abstained": False,
                         "citations": [], "unknown_citations": [], "reply": "My cat is Luna [E1].\n# FINAL ANSWER [ref:abc]: Luna"}]
        self.predictions = [{"question_id": "q1", "abstain": False, "answer": "Luna", "citations": []}]
        self.policy_result = {"policy_version": "TEST-ONLY-NOT-A-REAL-POLICY", "reactor_citations": [],
                              "fallback_citations": ["s1"], "unresolved_claims": [],
                              "supports": [{"claim": "Luna", "source_id": "s1", "evidence_index": 0, "role": "user",
                                            "span": "My cat is Luna.", "start": 6, "end": 21, "rule": "TEST_ONLY"}],
                              "final_citations": ["s1"]}

    def run_policy(self, policy=None):
        return evaluate_policy(self.questions, self.gold, [self.history], self.evidence,
                               self.results, self.predictions, policy or (lambda q, h, e, r: copy.deepcopy(self.policy_result)))

    def test_new_derivative_scored_separately_without_changing_historical_prediction(self):
        before = copy.deepcopy([self.results, self.predictions, self.evidence])
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            report, predictions = self.run_policy()
        self.assertEqual([self.results, self.predictions, self.evidence], before)
        self.assertEqual(predictions[0]["answer"], "Luna")
        self.assertEqual(predictions[0]["citations"], ["s1"])
        self.assertEqual(report["historical_actual_outputs_official_local"]["all"]["evidence_f1"], 0)
        self.assertEqual(report["new_policy_actual_outputs_official_local"]["all"]["evidence_f1"], 1)
        self.assertEqual(report["full_scope_new_policy_official_submission"]["all"]["evidence_f1"], .5)
        self.assertEqual(report["scope"]["available_output_coverage"], .5)
        self.assertEqual(report["attribution_counts"]["outputs_with_verified_fallback_citations"], 1)
        self.assertFalse(report["oracle_proxy"])

    def test_gold_never_passed_into_policy_and_only_affects_scoring(self):
        received = []
        def policy(*args):
            self.assertEqual(len(args), 4)
            self.assertNotIn("EVALUATION_ONLY_GOLD_SECRET", repr(args))
            received.append(copy.deepcopy(args))
            return self.policy_result
        self.run_policy(policy)
        self.gold[0]["answer"] = "EVALUATION_ONLY_GOLD_SECRET"
        report, _ = self.run_policy(policy)
        self.assertEqual(received[0], received[1])
        self.assertEqual(report["new_policy_actual_outputs_official_local"]["all"]["unjudged"], 1)

    def test_unresolved_claims_remain_visible(self):
        self.policy_result["unresolved_claims"] = ["age is unknown"]
        report, _ = self.run_policy()
        self.assertEqual(report["attribution_counts"]["outputs_with_unresolved_claims"], 1)
        self.assertEqual(report["per_question"][0]["unresolved_claims"], ["age is unknown"])

    def test_foreign_and_unsupplied_evidence_rejected(self):
        self.policy_result["final_citations"] = ["foreign"]
        with self.assertRaisesRegex(ValueError, "foreign-history"):
            self.run_policy()
        self.history["sessions"].append({"session_id": "foreign", "date": "2023-05-29"})
        with self.assertRaisesRegex(ValueError, "original supplied evidence"):
            self.run_policy()

    def test_no_answer_or_missing_provenance_rejected(self):
        del self.policy_result["supports"]
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.run_policy()
        self.results[0]["status"] = "timeout"
        with self.assertRaisesRegex(ValueError, "real completed"):
            self.run_policy()

    def test_original_prediction_cannot_be_rewritten_before_evaluation(self):
        self.predictions[0]["citations"] = ["s1"]
        with self.assertRaisesRegex(ValueError, "Historical prediction"):
            self.run_policy()

    def test_policy_cannot_misattribute_fallback_as_reactor_supplied(self):
        self.policy_result["reactor_citations"] = ["s1"]
        with self.assertRaisesRegex(ValueError, "Reactor-supplied"):
            self.run_policy()

    def test_dates_and_scope_are_preserved(self):
        self.evidence["q1"][0]["date"] = "2024-01-01"
        with self.assertRaisesRegex(ValueError, "source and date"):
            self.run_policy()

    def test_unverifiable_fallback_span_cannot_be_reported_as_verified(self):
        self.policy_result["supports"][0]["start"] = 7
        with self.assertRaisesRegex(ValueError, "offsets"):
            self.run_policy()
        self.policy_result["supports"] = []
        with self.assertRaisesRegex(ValueError, "lacks independently"):
            self.run_policy()

    def test_fabricated_reactor_metadata_rejected_even_if_adapter_reproduces_it(self):
        self.results[0]["citations"] = [{"label": "E1", "id": "s1", "date": "2023-05-29"}]
        self.predictions[0]["citations"] = ["s1"]
        with self.assertRaisesRegex(ValueError, "actual marked final answer"):
            self.run_policy()


if __name__ == "__main__":
    unittest.main()
