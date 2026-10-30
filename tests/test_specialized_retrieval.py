"""Gold independence, chronological neutrality and packing contracts."""
import unittest

from retrieval_specialized import METHODS, retrieve


class SpecializedRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.history = {"sessions": [
            {"session_id": f"s_{i}", "date": f"2023/01/{i+1:02}", "turns": [
                {"role": "user", "content": f"I bought bike number {i}."},
                {"role": "assistant", "content": "Your bike is excellent."}]}
            for i in range(10)]}

    def test_adaptive_routes_only_question_text(self):
        q = {"question": "How many bikes have I bought in total?"}
        self.assertEqual(len(retrieve(q, self.history)), 8)
        q.update(question_type="single-session-user", answer="secret", evidence=["other"])
        self.assertEqual(retrieve(q, self.history), retrieve({"question": q["question"]}, self.history))
        self.assertEqual(len(retrieve({"question": "Which bike did I buy?"}, self.history)), 4)

    def test_session_deduplication_and_no_recency_bias(self):
        result = retrieve({"question": "Which bike came first?"}, self.history, k=2)
        self.assertEqual([r["id"] for r in result], ["s_0", "s_1", "s_2", "s_3"])
        self.assertEqual(len({r["id"] for r in result}), len(result))

    def test_budget_provenance_and_roles(self):
        for method in METHODS:
            for budget in (1, 7, 35, 101, 12000):
                result = retrieve({"question": "How many bikes?"}, self.history,
                                  method=method, budget=budget)
                self.assertLessEqual(sum(len(r["text"]) for r in result), budget)
                for r in result:
                    s = next(s for s in self.history["sessions"] if s["session_id"] == r["id"])
                    self.assertEqual(r["date"], s["date"])
                    if budget == 12000:
                        self.assertIn("user:", r["text"])

    def test_long_hit_keeps_query_neighborhood(self):
        self.history["sessions"][0]["turns"] = [{"role": "user", "content":
            "padding " * 1000 + "My bike cost 750 dollars." + " padding" * 1000}]
        result = retrieve({"question": "How much did my bike cost?"}, self.history, k=1,
                          method="session", budget=200)
        self.assertIn("750 dollars", result[0]["text"])

    def test_empty_and_invalid(self):
        self.assertEqual(retrieve({"question": "quasar"}, self.history), [])
        for kwargs in ({"k": 0}, {"budget": 0}, {"method": "unknown"}):
            with self.assertRaises(ValueError):
                retrieve({"question": "bike"}, self.history, **kwargs)


if __name__ == "__main__":
    unittest.main()
