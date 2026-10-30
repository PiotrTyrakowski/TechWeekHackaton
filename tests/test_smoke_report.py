import unittest
from smoke_report import build_report


class SmokeReportTests(unittest.TestCase):
    def data(self):
        qs = [{"question_id": "q1", "question": "Name?"}, {"question_id": "q2", "question": "City?"}]
        gold = [{"question_id": q, "question_type": "single-session-user", "answer": a, "evidence": ["s1"], "abstain": False} for q, a in [("q1", "Luna"), ("q2", "London")]]
        return qs, gold

    def test_pending_is_incomplete_not_wrong(self):
        qs, gold = self.data()
        pred = [{"question_id": "q1", "answer": "Luna", "citations": [], "abstain": False}]
        attempts = [{"operation": "new_history", "exit_code": 0, "wall_s": 1, "result": {}}, {"operation": "question", "question_id": "q1", "exit_code": 0, "wall_s": 2, "result": {"retries": 2}}]
        report = build_report(qs, gold, pred, attempts, [], {})
        self.assertEqual(report["scope"]["missing"], 1)
        self.assertEqual(report["completed_only_metrics"]["all"]["correct"], 1)
        self.assertIsNone(report["per_question"][1]["official_local_result"])
        self.assertEqual(report["per_question"][0]["evidence_f1"], 0)
        self.assertEqual(report["operations"]["total_api_operations_observed"], 4)

    def test_full_scope_and_unjudged(self):
        qs, gold = self.data()
        pred = [{"question_id": q, "answer": a, "citations": ["s1"], "abstain": False} for q,a in [("q1", "Different"), ("q2", "London")]]
        report = build_report(qs, gold, pred, [], [], {})
        self.assertTrue(report["scope"]["complete"])
        self.assertTrue(report["per_question"][0]["manual_review"]["required"])
        self.assertFalse(report["per_question"][0]["manual_review"]["official_judge"])

    def test_duplicate_predictions_rejected(self):
        qs, gold = self.data()
        p = {"question_id": "q1", "answer": "Luna", "citations": [], "abstain": False}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_report(qs, gold, [p, p], [], [], {})

    def test_actual_citation_metrics_include_false_abstention_and_preload_cost(self):
        qs, gold = self.data()
        preds = [{"question_id": "q1", "answer": "Luna", "citations": ["s1"], "abstain": False},
                 {"question_id": "q2", "answer": "", "citations": [], "abstain": True}]
        attempts = [{"operation": "preload", "exit_code": 0, "wall_s": 4, "result": {"retries": 1}},
                    {"operation": "question", "exit_code": 3, "wall_s": 10, "result": {}}]
        results = [{"question_id": "q1", "latency_s": 7}, {"question_id": "q2", "latency_s": 3}]
        report = build_report(qs, gold, preds, attempts, results, {})
        self.assertEqual(report["completed_only_metrics"]["all"]["evidence_f1"], .5)
        self.assertEqual(report["per_question"][1]["evidence_recall"], 0)
        self.assertEqual(report["citation_diagnostics"]["final_answer_citation_coverage"], 1)
        self.assertEqual(report["operations"]["preload_attempts"], 1)
        self.assertEqual(report["operations"]["total_api_operations_observed"], 3)
        self.assertEqual(report["operations"]["client_invocation_failure_rate"], .5)
        self.assertEqual(report["successful_answer_latency_s"]["p50"], 5)

    def test_paired_reports_refuse_selection_mismatch_and_retain_missing(self):
        from compare_reactor import compare
        qs, gold = self.data()
        pred = {"question_id": "q1", "answer": "Luna", "citations": ["s1"], "abstain": False}
        a = build_report(qs, gold, [pred], [], [], {})
        b = build_report(qs, gold, [dict(pred, citations=[])], [], [], {})
        result = compare({"a": a, "b": b})
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["complete_pairs"], 1)
        self.assertEqual(result["paired_evidence_f1_delta"]["b"]["mean"], -1)
        with self.assertRaisesRegex(ValueError, "identical"):
            compare({"a": a, "b": dict(b, per_question=b["per_question"][:1])})

    def test_disjoint_history_reports_aggregate_without_cherry_picking(self):
        from compare_reactor import merge_reports
        qs, gold = self.data()
        pred = {"question_id": "q1", "answer": "Luna", "citations": ["s1"], "abstain": False}
        a = build_report(qs[:1], gold, [pred], [], [], {})
        b = build_report(qs[1:], gold, [], [], [], {})
        combined = merge_reports([a, b])
        self.assertEqual(combined["scope"], {"questions": 2, "completed": 1, "missing": 1, "complete": False})
        self.assertEqual(combined["completed_only_metrics"]["all"]["evidence_f1"], 1)
        with self.assertRaisesRegex(ValueError, "overlapping"):
            merge_reports([a, a])


if __name__ == "__main__":
    unittest.main()
