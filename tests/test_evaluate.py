import tempfile
import unittest
from pathlib import Path

from evaluate import answer_evaluation, partition, retrieval_metrics, load_retriever


class EvaluationTests(unittest.TestCase):
    def test_set_metrics_deduplicate_and_penalize_distractors(self):
        metrics = retrieval_metrics(["s1", "s1", "s3"], ["s1", "s2"])
        self.assertEqual(metrics["recall"], .5)
        self.assertEqual(metrics["precision"], .5)
        self.assertEqual(metrics["evidence_f1"], .5)
        self.assertEqual(metrics["all_hit"], 0)

    def test_unanswerable_has_no_evidence_metric(self):
        self.assertIsNone(retrieval_metrics(["s1"], [])["evidence_f1"])

    def test_fixed_partition(self):
        values = [partition(f"q{i}") for i in range(100)]
        self.assertEqual(values, [partition(f"q{i}") for i in range(100)])
        self.assertEqual(set(values), {"development", "validation"})

    def test_explicit_worktree_file_beats_same_named_import_and_keeps_relative_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'model.txt').write_text('isolated-version')
            path = root / 'retrieval_calibrated.py'
            path.write_text("from pathlib import Path\nVERSION = (Path(__file__).parent/'model.txt').read_text()\n")
            module = load_retriever('retrieval_calibrated', path)
            self.assertEqual(module.VERSION, 'isolated-version')
            self.assertEqual(Path(module.__file__).resolve(), path.resolve())

    def test_answer_scoring_rejects_other_history_citation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "histories.jsonl").write_text('{"history_id":"h1","sessions":[{"session_id":"s1"}]}\n')
            (root / "predictions.jsonl").write_text('{"question_id":"q1","answer":"value","abstain":false,"citations":["s2"]}\n')
            with self.assertRaisesRegex(ValueError, "outside corresponding history"):
                answer_evaluation(root, root / "predictions.jsonl", {"q1": {"history_id": "h1"}}, {}, root)


if __name__ == "__main__":
    unittest.main()
