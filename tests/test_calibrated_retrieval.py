"""Contract checks for frozen calibration and label-free inference."""
import copy
import unittest
from unittest.mock import patch

import retrieval_calibrated as calibrated


class CalibratedRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.question = {"question_id": "ignored", "question": "What degree did I graduate with?"}
        self.history = {"history_id": "ignored", "sessions": [
            {"session_id": "s1", "date": "2023/01/01", "turns": [
                {"role": "user", "content": "I graduated with a business degree."},
                {"role": "assistant", "content": "Congratulations on graduating!"}]},
            {"session_id": "s2", "date": "2023/01/02", "turns": [
                {"role": "user", "content": "My degree helps at work."}]}]}
        self.artifact = {"features": calibrated.FEATURES, "pool": 32,
            "mean": [0]*len(calibrated.FEATURES), "scale": [1]*len(calibrated.FEATURES),
            "weights": [0]*len(calibrated.FEATURES), "intercept": 0,
            "mass_multiplier": 1.0}

    def test_identifiers_and_extra_labels_do_not_change_features(self):
        before = calibrated.candidates(self.question, self.history)
        q, h = copy.deepcopy(self.question), copy.deepcopy(self.history)
        q.update(question_id="other", history_id="other", answer="secret", evidence=["s2"])
        h["history_id"] = "other"
        for s in h["sessions"]:
            s["session_id"] += "renamed"
        self.assertEqual(before, calibrated.candidates(q, h))

    def test_output_budget_identity_and_role(self):
        with patch.object(calibrated, "model", return_value=self.artifact):
            result = calibrated.retrieve(self.question, self.history, k=1, budget=31)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "s1")
        self.assertEqual(result[0]["date"], "2023/01/01")
        self.assertTrue(result[0]["text"].startswith("user:"))
        self.assertLessEqual(sum(len(p["text"]) for p in result), 31)

    def test_expected_f1_selects_clear_single_and_broad_pair(self):
        rows = [{"si": i} for i in range(3)]
        self.assertEqual(len(calibrated.select(rows, [.95, .01, .01])), 1)
        self.assertEqual(len(calibrated.select(rows, [.95, .9, .01])), 2)
        self.assertEqual(len(calibrated.select(rows, [.95, .9, .01], limit=1)), 1)

    def test_empty_and_invalid_arguments(self):
        with patch.object(calibrated, "model", return_value=self.artifact):
            self.assertEqual(calibrated.retrieve(self.question, {"sessions": []}), [])
            with self.assertRaises(ValueError):
                calibrated.retrieve(self.question, self.history, k=0)


if __name__ == "__main__":
    unittest.main()
