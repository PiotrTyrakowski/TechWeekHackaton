"""Retrieval contract tests use deterministic fake embeddings; no model downloads."""
import os
import unittest
from unittest.mock import patch

import retrieval_dense as dense
import retrieval


class DenseContractTests(unittest.TestCase):
    def setUp(self):
        self.history = {"sessions": [
            {"session_id": "s1", "date": "today", "turns": [
                {"role": "user", "content": "My commute takes thirty minutes."}]},
            {"session_id": "s2", "date": "yesterday", "turns": [
                {"role": "assistant", "content": "Coffee costs five dollars."}]}]}
        self.question = {"question": "How long is my commute?"}

    def test_history_dates_and_budget(self):
        ranking = [(1.0, 0, 0), (.5, 1, 0)]
        with patch.object(dense, "_dense_rank", return_value=ranking):
            result = dense.retrieve(self.question, self.history, k=2, budget=30)
            self.assertEqual([r["date"] for r in result], ["today", "yesterday"])
            self.assertLessEqual(sum(len(r["text"]) for r in result), 30)
            self.history["sessions"][0]["date"] = "different history date"
            self.assertEqual(dense.retrieve(self.question, self.history)[0]["date"],
                             "different history date")

    def test_roles_and_hybrid(self):
        with patch.object(dense, "_dense_rank", return_value=[(1.0, 0, 0), (.5, 1, 0)]):
            result = dense.retrieve(self.question, self.history, method="dense-hybrid", k=1)
            self.assertEqual(result[0]["id"], "s1")
            self.assertTrue(result[0]["text"].startswith("user: "))

    def test_validation_and_empty(self):
        for kwargs in ({"k": 0}, {"budget": 0}, {"method": "wrong"}):
            with self.assertRaises(ValueError):
                dense.retrieve(self.question, self.history, **kwargs)
        self.assertEqual(dense.retrieve(self.question, {"sessions": []}), [])

    def test_optional_method_routes_without_loading_backend_until_requested(self):
        with patch.object(dense, '_dense_rank', return_value=[(1.0, 0, 0)]):
            result = retrieval.retrieve(self.question, self.history, method='dense-hybrid')
            self.assertEqual(result[0]['id'], 's1')

    def test_empty_lexical_shortlist_does_not_expand_to_entire_history(self):
        with patch.dict(os.environ, {'DENSE_CANDIDATE_LIMIT': '16'}), patch.object(
                dense, '_encoder', side_effect=AssertionError('unexpected model work')):
            self.assertEqual(dense.retrieve({'question': 'quasar'}, self.history), [])


if __name__ == "__main__":
    unittest.main()
