"""Citation provenance and deterministic baseline contract checks."""
import unittest

from official.reactor.examples.run_benchmark import retrieve as organizer_retrieve
from retrieval import METHODS, _hybrid_rank, retrieve


class RetrievalContract(unittest.TestCase):
    def setUp(self):
        self.history = {"sessions": [
            {"session_id": "s_cat", "date": "2023/05/20 (Sat) 02:21", "turns": [
                {"role": "user", "content": "I adopted three orange cats."},
                {"role": "assistant", "content": "Feed those cats wet food."}]},
            {"session_id": "s_dog", "date": "2023/05/21 (Sun) 02:21", "turns": [
                {"role": "user", "content": "My dog is black."}]}]}
        self.question = {"question": "How many orange cats did I adopt?"}

    def test_exact_official_baseline(self):
        for k in (1, 4, 8):
            self.assertEqual(retrieve(self.question, self.history, k=k, method="official"),
                             organizer_retrieve(self.question, self.history, k=k))

    def test_dates_belong_to_history_and_citations_are_sessions(self):
        for method in METHODS:
            a = retrieve(self.question, self.history, method=method)
            self.history["sessions"][0]["date"] = "2024/01/01 (Mon) 00:00"
            b = retrieve(self.question, self.history, method=method)
            self.assertTrue(a)
            self.assertTrue(all(p["id"] == "s_cat" for p in b))
            self.assertTrue(all(p["date"] == "2024/01/01 (Mon) 00:00" for p in b))

    def test_assistant_only_answer_is_retrievable(self):
        q = {"question": "What food did you recommend?"}
        for method in METHODS:
            passages = retrieve(q, self.history, method=method)
            self.assertTrue(any("wet food" in p["text"] for p in passages))

    def test_empty_match_and_budget(self):
        self.assertEqual(retrieve({"question": "quasar"}, self.history), [])
        for method in ("bm25", "bm25-context", "hybrid"):
            passages = retrieve(self.question, self.history, method=method, budget=35)
            self.assertLessEqual(sum(len(p["text"]) for p in passages), 35)

    def test_hybrid_fuses_rankings_and_keeps_history_ties_stable(self):
        history = {"sessions": [{"session_id": "s_1", "date": "date", "turns": [
            {"role": "user", "content": "orange cats"},
            {"role": "assistant", "content": "orange"},
            {"role": "user", "content": "cats"}]}]}
        # Keyword order is turns 0,1,2; BM25 order is 1,0,2.
        fused = _hybrid_rank({"question": "orange cats"}, history,
                             [(10, 0, 1), (5, 0, 0), (1, 0, 2)])
        self.assertEqual([(si, ti) for _, si, ti in fused], [(0, 0), (0, 1), (0, 2)])
        self.assertAlmostEqual(fused[0][0], 1/61 + 1/62)


if __name__ == "__main__":
    unittest.main()
