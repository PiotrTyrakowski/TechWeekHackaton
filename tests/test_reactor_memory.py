import unittest
from unittest.mock import patch

import reactor_memory as memory


class MemoryTests(unittest.TestCase):
    history = {"history_id": "h_a", "sessions": [
        {"session_id": "s_a", "date": "2023/05/20 (Sat) 02:21", "turns": []},
        {"session_id": "s_b", "date": "2023/05/27 (Sat) 10:05", "turns": []}]}
    questions = [{"question_id": "q_a", "history_id": "h_a", "question": "cat"},
                 {"question_id": "q_b", "history_id": "h_a", "question": "wedding"}]
    early = {"id": "s_a", "date": "2023/05/20 (Sat) 02:21", "text": "user: The wedding is in May."}
    late = {"id": "s_b", "date": "2023/05/27 (Sat) 10:05", "text": "assistant: Consider June instead."}

    def test_public_question_pool_is_deduplicated_and_chronological(self):
        with patch.object(memory, "retrieve", side_effect=[[self.late, self.early], [self.early]]):
            parts = memory.prepare_memory(self.history, self.questions)
        text = "".join(parts)
        self.assertEqual(text.count(self.early["text"]), 1)
        self.assertLess(text.index(self.early["text"]), text.index(self.late["text"]))
        self.assertIn("assistant: Consider June instead.", text)
        self.assertIn("[session s_a, 2023/05/20 (Sat) 02:21]", text)
        self.assertNotIn("[E1]", text)

    def test_serialized_total_and_each_part_include_header_in_limit(self):
        big_a = dict(self.early, text="user: " + "a" * 900)
        big_b = dict(self.late, text="assistant: " + "b" * 900)
        with patch.object(memory, "retrieve", return_value=[big_a, big_b]):
            parts = memory.prepare_memory(self.history, self.questions[:1], budget=3500, max_chars=1800)
        self.assertEqual(len(parts), 2)
        self.assertLessEqual(sum(map(len, parts)), 3500)
        self.assertTrue(all(len(p) <= 1800 and p.startswith(memory.PREFIX) for p in parts))
        self.assertTrue(any(big_a["text"] in p for p in parts))
        self.assertTrue(any(big_b["text"] in p for p in parts))

    def test_wrong_user_or_source_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "dataset history"):
            memory.prepare_memory(self.history, [dict(self.questions[0], history_id="h_other")])
        with patch.object(memory, "retrieve", return_value=[dict(self.early, date="2024-01-01")]):
            with self.assertRaisesRegex(ValueError, "history-local"):
                memory.prepare_memory(self.history, self.questions[:1])

    def test_no_evidence_means_no_preload_and_oversized_is_not_truncated(self):
        with patch.object(memory, "retrieve", return_value=[]):
            self.assertEqual(memory.prepare_memory(self.history, self.questions), [])
        with patch.object(memory, "retrieve", return_value=[dict(self.early, text="x" * 5000)]):
            self.assertEqual(memory.prepare_memory(self.history, self.questions, max_chars=1000), [])

    def test_excerpts_in_one_part_do_not_reserve_extra_headers(self):
        blocks = [f"[session {e['id']}, {e['date']}]\n{e['text']}\n\n"
                  for e in (self.early, self.late)]
        exact = len(memory.PREFIX) + sum(map(len, blocks))
        with patch.object(memory, "retrieve", return_value=[self.late, self.early]):
            parts = memory.prepare_memory(self.history, self.questions[:1], budget=exact, max_chars=exact)
        self.assertEqual(parts, [memory.PREFIX + "".join(blocks)])

    def test_chronological_repacking_stays_bounded_at_boundary(self):
        with patch.object(memory, "retrieve", return_value=[self.late, self.early]):
            parts = memory.prepare_memory(self.history, self.questions[:1],
                                          budget=len(memory.PREFIX) + 100, max_chars=len(memory.PREFIX) + 100)
        self.assertLessEqual(sum(map(len, parts)), len(memory.PREFIX) + 100)
        self.assertEqual(parts, [memory.PREFIX +
                         f"[session {self.late['id']}, {self.late['date']}]\n{self.late['text']}\n\n"])


if __name__ == "__main__":
    unittest.main()
