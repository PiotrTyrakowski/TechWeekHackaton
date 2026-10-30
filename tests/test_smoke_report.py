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


if __name__ == "__main__":
    unittest.main()
