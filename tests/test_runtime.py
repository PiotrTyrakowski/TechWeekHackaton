"""Mock client lifecycle tests; these are not Reactor benchmark predictions."""
import json
from argparse import Namespace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.questions = [
            {"question_id": "q1", "history_id": "h1", "question": "Which color?", "question_date": "2023-05-30"},
            {"question_id": "q2", "history_id": "h1", "question": "Which color again?", "question_date": "2023-05-30"},
            {"question_id": "q3", "history_id": "h2", "question": "Which color?", "question_date": "2023-05-30"},
        ]
        self.histories = [{"history_id": f"h{i}", "sessions": [
            {"session_id": f"s{i}", "date": "2023-05-20", "turns": [
                {"role": "user", "content": "My color is blue"}]}]} for i in (1, 2)]
        for name, values in [("questions", self.questions), ("histories", self.histories)]:
            (self.root / (name + ".jsonl")).write_text("".join(json.dumps(x) + "\n" for x in values))
        self.argv = ["--questions", str(self.root / "questions.jsonl"), "--histories",
                     str(self.root / "histories.jsonl"), "--out-dir", str(self.root / "run"), "--limit", "0",
                     "--agent-id", "unit-test-agent"]
        self.calls = []

    def client(self, args, extra):
        self.calls.append(extra)
        if "--new-history" in extra:
            return {"status": "history", "history_id": f"reactor{len(self.calls)}"}, 0, .01
        qid = extra[extra.index("--question-id") + 1]
        hid = extra[extra.index("--history") + 1]
        return {"status": "answered", "question_id": qid, "history_id": hid,
                "answer": "Blue [E1].", "abstained": False,
                "citations": [{"label": "E1", "id": "s2" if qid == "q3" else "s1"}]}, 0, .01

    def test_dry_run_never_invokes_client(self):
        with patch.object(runtime, "invoke", side_effect=AssertionError("API called")):
            self.assertEqual(runtime.main(self.argv), 0)
        plan = json.loads((self.root / "run/plan.json").read_text())
        self.assertEqual(len(plan["question_ids"]), 3)

    def test_jsonl_preserves_unicode_line_separators_in_content(self):
        path = self.root / "unicode.jsonl"
        values = [{"text": "before\u2028middle\u0085after"}, {"text": "second"}]
        path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in values))
        self.assertEqual(runtime.read_jsonl(path), values)

    def test_sequential_histories_predictions_and_resume(self):
        with patch.dict(os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), patch.object(
                runtime, "invoke", side_effect=self.client), patch.object(
                runtime.official_client, "environment_problem", return_value=None):
            self.assertEqual(runtime.main(self.argv + ["--execute"]), 0)
            self.assertEqual(len(self.calls), 5)
            self.assertEqual(self.calls[1][1], self.calls[2][1])
            self.assertNotEqual(self.calls[2][1], self.calls[4][1])
            self.assertEqual(runtime.main(self.argv + ["--execute"]), 0)
            self.assertEqual(len(self.calls), 5)
        preds = runtime.read_jsonl(self.root / "run/predictions.jsonl")
        self.assertEqual([x["question_id"] for x in preds], ["q1", "q2", "q3"])
        self.assertEqual(preds[0]["answer"], "Blue.")

    def test_stop_after_preserves_manifest_for_continuation(self):
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=self.client), patch.object(
                runtime.official_client, 'environment_problem', return_value=None):
            self.assertEqual(runtime.main(self.argv + ['--execute', '--stop-after', '1']), 0)
            before = (self.root / 'run/plan.json').read_bytes()
            self.assertEqual(len(self.calls), 2)
            self.assertEqual(runtime.main(self.argv + ['--execute']), 0)
            self.assertEqual(len(self.calls), 5)
            self.assertEqual((self.root / 'run/plan.json').read_bytes(), before)

    def test_timeout_stops_and_is_not_retried_on_resume(self):
        def timeout(args, extra):
            if "--new-history" in extra:
                return self.client(args, extra)
            self.calls.append(extra)
            return {"status": "timeout", "question_id": "q1"}, 3, .01
        with patch.dict(os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), patch.object(
                runtime, "invoke", side_effect=timeout), patch.object(
                runtime.official_client, "environment_problem", return_value=None):
            self.assertEqual(runtime.main(self.argv + ["--execute"]), 2)
            self.assertEqual(runtime.main(self.argv + ["--execute"]), 2)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse((self.root / "run/results.jsonl").exists())

    def test_rejects_citation_from_another_history(self):
        r = {"status": "answered", "question_id": "q1", "answer": "Blue [E1]",
             "citations": [{"label": "E1", "id": "s2"}], "abstained": False}
        with self.assertRaises(ValueError):
            runtime.prediction(r, self.questions[0], self.histories[0])

    def test_preserves_uncited_reactor_answer_for_official_scoring(self):
        r = {"status": "answered", "question_id": "q1", "answer": "Blue",
             "citations": [], "abstained": False}
        pred = runtime.prediction(r, self.questions[0], self.histories[0])
        self.assertEqual(pred['answer'], 'Blue')
        self.assertEqual(pred['citations'], [])

    def test_recovers_durable_answer_without_reasking_after_local_failure(self):
        with patch.dict(os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), patch.object(
                runtime, "invoke", side_effect=self.client), patch.object(
                runtime.official_client, "environment_problem", return_value=None):
            with patch.object(runtime, 'prediction', side_effect=ValueError('local validation failed')):
                self.assertEqual(runtime.main(self.argv + ['--execute']), 2)
            self.assertEqual(len(self.calls), 2)
            self.assertEqual(runtime.main(self.argv + ['--execute']), 0)
            self.assertEqual(len(self.calls), 5)  # original reset+answer, no repeated q1
            self.assertEqual(len(runtime.read_jsonl(self.root / 'run/results.jsonl')), 3)

    def test_closed_retry_requires_opt_in_and_preserves_history(self):
        def closed_once(args, extra):
            if len(self.calls) == 1:
                self.calls.append(extra)
                return {'status': 'closed', 'question_id': 'q1'}, 5, .01
            return self.client(args, extra)
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=closed_once), patch.object(
                runtime.official_client, 'environment_problem', return_value=None):
            self.assertEqual(runtime.main(self.argv + ['--execute']), 2)
            self.assertEqual(runtime.main(self.argv + ['--execute']), 2)
            self.assertEqual(len(self.calls), 2)
            self.assertEqual(runtime.main(self.argv + ['--execute', '--retry-closed']), 0)
            self.assertEqual(self.calls[1][1], self.calls[2][1])
            self.assertEqual(len(self.calls), 6)

    def test_restarts_changed_history_once_before_any_answer_succeeded(self):
        def changed_once(args, extra):
            if len(self.calls) == 1:
                self.calls.append(extra)
                return {'status': 'refused', 'code': 'history_changed', 'question_id': 'q1'}, 4, .01
            return self.client(args, extra)
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=changed_once), patch.object(
                runtime.official_client, 'environment_problem', return_value=None):
            self.assertEqual(runtime.main(self.argv + ['--execute']), 2)
            self.assertEqual(runtime.main(self.argv + ['--execute', '--restart-interrupted-history']), 0)
            self.assertEqual(len(self.calls), 7)
            self.assertNotEqual(self.calls[1][1], self.calls[3][1])

    def test_documented_current_history_recovery_never_adds_reset(self):
        def changed_once(args, extra):
            if len(self.calls) == 1:
                self.calls.append(extra)
                return {'status': 'refused', 'code': 'history_changed', 'question_id': 'q1',
                        'current_history_id': 'server-current'}, 4, .01
            return self.client(args, extra)
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=changed_once), patch.object(
                runtime.official_client, 'environment_problem', return_value=None):
            self.assertEqual(runtime.main(self.argv + ['--execute']), 2)
            self.assertEqual(runtime.main(self.argv + ['--execute', '--adopt-server-history']), 0)
            self.assertEqual(len(self.calls), 6)
            self.assertEqual(self.calls[2][1], 'server-current')
            self.assertEqual(sum('--new-history' in c for c in self.calls), 2)

    def test_server_history_adoption_rejected_after_answer_in_same_history(self):
        def changed_second(args, extra):
            if '--question-id' in extra and extra[extra.index('--question-id') + 1] == 'q2':
                self.calls.append(extra)
                return {'status': 'refused', 'code': 'history_changed', 'question_id': 'q2',
                        'current_history_id': 'foreign-current'}, 4, .01
            return self.client(args, extra)
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=changed_second), patch.object(
                runtime.official_client, 'environment_problem', return_value=None):
            self.assertEqual(runtime.main(self.argv + ['--execute']), 2)
            calls = len(self.calls)
            self.assertEqual(runtime.main(self.argv + ['--execute', '--adopt-server-history']), 2)
            self.assertEqual(len(self.calls), calls)

    def test_client_upgrade_requires_explicit_flag_and_no_prior_answers(self):
        self.assertEqual(runtime.main(self.argv), 0)
        path = self.root / 'run/plan.json'
        old = json.loads(path.read_text())
        old['client_sha256'] = 'old-client-hash'
        path.write_text(json.dumps(old))
        self.assertEqual(runtime.main(self.argv), 2)
        self.assertEqual(runtime.main(self.argv + ['--upgrade-client']), 0)
        self.assertTrue((self.root / 'run/client-upgrades.jsonl').exists())

    def test_redacts_secret_recursively(self):
        with patch.dict(os.environ, {"REACTOR_ACCESS_KEY": "test-key"}):
            self.assertEqual(runtime.redact({"x": ["error test-key"]}), {"x": ["error [REDACTED]"]})

    def test_rejects_wrong_evidence_label_mapping(self):
        with self.assertRaises(ValueError):
            runtime.validate_evidence_citations({"citations": [{"label": "E2", "id": "s1"}]},
                                                [{"id": "s1"}])

    def test_crash_before_reset_response_is_not_automatically_retried(self):
        with patch.dict(os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), patch.object(
                runtime, "invoke", side_effect=RuntimeError("simulated process crash")), patch.object(
                runtime.official_client, "environment_problem", return_value=None):
            with self.assertRaises(RuntimeError):
                runtime.main(self.argv + ["--execute"])
        with patch.dict(os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), patch.object(
                runtime, "invoke", side_effect=AssertionError("must not call")):
            self.assertEqual(runtime.main(self.argv + ["--execute"]), 2)

    def test_retains_only_histories_for_selected_questions(self):
        args = Namespace(questions=self.root / "questions.jsonl", histories=self.root / "histories.jsonl",
                         question_ids=None, limit=1, method="official", k=4, budget=12000,
                         max_chars=16000, client=runtime.ROOT / "official/reactor/client.py",
                         base_url="https://example.test", agent_id="test")
        with patch.object(runtime, "read_jsonl", wraps=runtime.read_jsonl) as reader:
            questions, histories, _, _ = runtime.prepare(args)
            self.assertEqual(len(questions), 1)
            self.assertEqual(set(histories), {"h1"})
            self.assertEqual(reader.call_count, 1)  # histories must never be eagerly loaded

    def test_agent_execution_lock_excludes_other_output_directories(self):
        with patch.object(runtime, "ROOT", self.root):
            with runtime.execution_lock("https://example.test/", "agent"):
                with self.assertRaises(ValueError):
                    with runtime.execution_lock("https://example.test", "agent"):
                        self.fail("second execution lock acquired")
                with runtime.execution_lock("https://example.test", "other-agent"):
                    pass


if __name__ == "__main__":
    unittest.main()
