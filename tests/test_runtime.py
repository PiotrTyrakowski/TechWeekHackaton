"""Mock client lifecycle tests; these are not Reactor benchmark predictions."""
import json
from argparse import Namespace
from datetime import datetime, timezone
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
                     "--agent-id", "unit-test-" + self.root.name, "--exclusive-access",
                     "--access-window", str(self.root / "window.json")]
        self.window = {"owner": "unit-test-runner", "agreed_with": ["unit-test-teammate"],
                       "starts_at": "2000-01-01T00:00:00Z", "ends_at": "2100-01-01T00:00:00Z",
                       "base_url": "https://t07.api.reactor-hackathon.rxai.dev",
                       "agent_id": "unit-test-" + self.root.name}
        (self.root / "window.json").write_text(json.dumps(self.window))
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

    def memory_client(self, args, extra):
        if '--text' in extra:
            self.calls.append(extra)
            return {'status': 'reply', 'reply': 'OK',
                    'history_id': extra[extra.index('--history') + 1]}, 0, .01
        return self.client(args, extra)

    def test_memory_preloads_once_per_history_and_never_becomes_prediction(self):
        args = self.argv + ['--execute', '--memory-mode', 'targeted']
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=self.memory_client):
            self.assertEqual(runtime.main(args + ['--stop-after', '1']), 0)
            self.assertEqual(len(self.calls), 3)  # reset, ledger, question
            self.assertEqual(runtime.main(args), 0)
        self.assertEqual(len(self.calls), 7)  # two resets, two ledgers, three questions
        self.assertEqual(len([call for call in self.calls if '--text' in call]), 2)
        self.assertEqual(len(runtime.read_jsonl(self.root / 'run/results.jsonl')), 3)
        self.assertEqual(len(runtime.read_jsonl(self.root / 'run/predictions.jsonl')), 3)
        attempts = runtime.read_jsonl(self.root / 'run/attempts.jsonl')
        self.assertEqual(len([a for a in attempts if a['operation'] == 'preload']), 2)

    def test_memory_timeout_stops_without_replaying_part(self):
        args = self.argv + ['--execute', '--memory-mode', 'targeted']
        def timeout(args, extra):
            if '--text' in extra:
                self.calls.append(extra)
                return {'status': 'timeout'}, 3, .01
            return self.client(args, extra)
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=timeout):
            self.assertEqual(runtime.main(args), 2)
            self.assertEqual(runtime.main(args), 2)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(runtime.read_jsonl(self.root / 'run/predictions.jsonl'), [])
        state = json.loads((self.root / 'run/checkpoint.json').read_text())
        self.assertEqual(state['pending']['operation'], 'preload')

    def test_durable_memory_reply_recovers_without_reloading(self):
        args = self.argv + ['--execute', '--memory-mode', 'targeted']
        original = runtime.atomic_json
        def fail_after_preload(path, value):
            if Path(path).name == 'checkpoint.json' and value.get('memory_completed') == 1 and value.get('pending') is None:
                raise OSError('crash after memory reply fsync')
            return original(path, value)
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=self.memory_client):
            with patch.object(runtime, 'atomic_json', side_effect=fail_after_preload):
                self.assertEqual(runtime.main(args), 2)
            self.assertEqual(len(self.calls), 2)
            self.assertEqual(runtime.main(args), 0)
        self.assertEqual(len(self.calls), 7)

    def test_wrong_history_memory_reply_is_never_accepted(self):
        args = self.argv + ['--execute', '--memory-mode', 'targeted']
        def foreign(args, extra):
            if '--text' in extra:
                self.calls.append(extra)
                return {'status': 'reply', 'reply': 'OK', 'history_id': 'foreign'}, 0, .01
            return self.client(args, extra)
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=foreign):
            self.assertEqual(runtime.main(args), 2)
            self.assertEqual(runtime.main(args), 2)
        self.assertEqual(len(self.calls), 2)

    def test_dry_run_never_invokes_client(self):
        with patch.object(runtime, "invoke", side_effect=AssertionError("API called")):
            self.assertEqual(runtime.main(self.argv), 0)
        plan = json.loads((self.root / "run/plan.json").read_text())
        self.assertEqual(len(plan["question_ids"]), 3)

    def test_live_execution_requires_exclusive_window_confirmation(self):
        args = [x for x in self.argv if x != '--exclusive-access']
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=AssertionError('must not call shared agent')):
            self.assertEqual(runtime.main(args + ['--execute']), 2)

    def test_bare_boolean_does_not_authorize_shared_agent(self):
        args = self.argv[:-2]
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=AssertionError('must not call shared agent')):
            self.assertEqual(runtime.main(args + ['--execute']), 2)

    def test_window_identity_timezone_start_expiry_and_request_reserve(self):
        args = Namespace(exclusive_access=True, access_window=self.root / "window.json",
                         base_url=self.window['base_url'], agent_id=self.window['agent_id'], timeout=300)
        now = datetime(2026, 10, 30, 22, 0, tzinfo=timezone.utc)
        variants = [
            {"agent_id": "another-agent"}, {"agreed_with": []},
            {"starts_at": "2026-10-30T23:00:00Z"}, {"ends_at": "2026-10-30T21:00:00Z"},
            {"ends_at": "2026-10-30T22:05:00Z"}, {"starts_at": "2026-10-30T20:00:00"},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                args.access_window.write_text(json.dumps({**self.window, **variant}))
                with self.assertRaises(ValueError):
                    runtime.access_window(args, now=now)
        args.access_window.write_text(json.dumps({**self.window, "ends_at": "2026-10-30T22:05:15Z"}))
        self.assertEqual(runtime.access_window(args, now=now)['owner'], self.window['owner'])

    def test_window_expiring_between_operations_stops_before_next_pending(self):
        checks = 0
        original = runtime.access_window
        def expire(args, now=None):
            nonlocal checks
            checks += 1
            if checks >= 3:
                raise ValueError('exclusive access window expired')
            return original(args, now)
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=self.client), patch.object(runtime, 'access_window', side_effect=expire):
            self.assertEqual(runtime.main(self.argv + ['--execute']), 2)
        self.assertEqual(len(self.calls), 1)  # reset completed; first question never sent
        state = json.loads((self.root / 'run/checkpoint.json').read_text())
        self.assertIsNone(state['pending'])

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

    def test_recovers_durable_reset_without_resetting_again(self):
        original = runtime.atomic_json
        def fail_after_reset(path, value):
            if Path(path).name == 'checkpoint.json' and value.get('reactor_history') and value.get('pending') is None:
                raise OSError('crash after reset response fsync')
            return original(path, value)
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=self.client):
            with patch.object(runtime, 'atomic_json', side_effect=fail_after_reset):
                self.assertEqual(runtime.main(self.argv + ['--execute']), 2)
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(runtime.main(self.argv + ['--execute']), 0)
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(len([call for call in self.calls if '--new-history' in call]), 2)

    def test_stale_successful_reset_cannot_resolve_a_new_uncertain_reset(self):
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=self.client):
            self.assertEqual(runtime.main(self.argv + ['--execute', '--stop-after', '1']), 0)
        state_path = self.root / 'run/checkpoint.json'
        state = json.loads(state_path.read_text())
        state['pending'] = {'operation': 'new_history', 'dataset_history': 'h1', 'request_id': 'new-uncertain-reset'}
        state_path.write_text(json.dumps(state))
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=AssertionError('must not retry reset')):
            self.assertEqual(runtime.main(self.argv + ['--execute']), 2)

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

    def test_unknown_current_history_is_never_adopted(self):
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
            self.assertEqual(runtime.main(self.argv + ['--execute', '--adopt-server-history']), 2)
            self.assertEqual(len(self.calls), 2)
            state = json.loads((self.root / 'run/checkpoint.json').read_text())
            self.assertEqual(state['reactor_history'], 'reactor1')

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
        self.assertEqual(runtime.redact('error rxk_example_not_a_real_key'), 'error [REDACTED]')

    def test_successful_transport_diagnostics_are_preserved_and_redacted(self):
        args = Namespace(client=Path('client.py'), base_url=self.window['base_url'],
                         agent_id=self.window['agent_id'], timeout=300, exclusive_access=True,
                         access_window=self.root / 'window.json')
        proc = Namespace(stdout=json.dumps({'status': 'history', 'history_id': 'r1'}),
                         stderr='transport ack=true rxk_example_not_real', returncode=0)
        with patch.object(runtime.subprocess, 'run', return_value=proc):
            result, code, _ = runtime.invoke(args, ['--new-history'])
        self.assertEqual(code, 0)
        self.assertEqual(result['client_stderr'], 'transport ack=true [REDACTED]')

    def test_malformed_zero_exit_client_is_a_failure(self):
        args = Namespace(client=Path('client.py'), base_url=self.window['base_url'],
                         agent_id=self.window['agent_id'], timeout=300, exclusive_access=True,
                         access_window=self.root / 'window.json')
        with patch.object(runtime.subprocess, 'run', return_value=Namespace(stdout='bad', stderr='', returncode=0)):
            result, code, _ = runtime.invoke(args, ['--new-history'])
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'error')

    def test_revalidates_stored_final_citations_on_resume(self):
        with patch.dict(os.environ, {'REACTOR_ACCESS_KEY': 'test-key'}), patch.object(
                runtime, 'invoke', side_effect=self.client):
            self.assertEqual(runtime.main(self.argv + ['--execute', '--stop-after', '1']), 0)
        results = self.root / 'run/results.jsonl'
        stored = runtime.read_jsonl(results)[0]
        stored['answer'] = 'Blue [E2]'
        results.write_text(json.dumps(stored) + '\n')
        with patch.object(runtime, 'invoke', side_effect=AssertionError('must not send')):
            self.assertEqual(runtime.main(self.argv), 2)

    def test_abstention_must_match_actual_reactor_final_answer(self):
        result = {'status': 'answered', 'question_id': 'q1', 'answer': 'Blue', 'abstained': True}
        with self.assertRaises(ValueError):
            runtime.prediction(result, self.questions[0], self.histories[0])

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
