"""Full local path with only HTTP/WS transports replaced, never a live agent."""
import io
import json
import re
import subprocess
import tempfile
import unittest
from contextlib import asynccontextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import reactor_client
import runtime
from official import score


class ReactorEndToEndTests(unittest.TestCase):
    def test_preload_stateful_questions_official_parser_predictions_and_scorer(self):
        self.exercise_pipeline()

    def test_timeout_recovery_waits_on_real_protocol_and_uses_a_fresh_ref(self):
        self.exercise_pipeline(interrupted=True)

    def exercise_pipeline(self, interrupted=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            date = "2023/05/30 (Tue) 12:18"
            histories = [{"history_id": "h_a", "sessions": [
                {"session_id": "s_cat", "date": date, "turns": [
                    {"role": "user", "content": "My cat is Luna 🐈.\u2028I adopted her."}]}]},
                {"history_id": "h_b", "sessions": [
                    {"session_id": "s_tea", "date": date, "turns": [
                        {"role": "assistant", "content": "Tea recommendation: green tea."}]}]}]
            questions = [{"question_id": "q1", "history_id": "h_a", "question": "cat name?", "question_date": date},
                         {"question_id": "q2", "history_id": "h_a", "question": "cat's hamster name?", "question_date": date},
                         {"question_id": "q3", "history_id": "h_b", "question": "tea recommendation?", "question_date": date}]
            for name, rows in (("histories", histories), ("questions", questions)):
                (root / (name + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in rows))
            now = datetime.now(timezone.utc)
            (root / "window.json").write_text(json.dumps({"owner": "simulation", "agreed_with": ["test-fixture"],
                "starts_at": (now - timedelta(minutes=1)).isoformat(), "ends_at": (now + timedelta(hours=1)).isoformat(),
                "base_url": "http://127.0.0.1", "agent_id": "fake"}))
            resets, messages, cycle = [], [], [0]
            failed_refs, retry_refs, pending_refusals = [], [], []

            def reset(*args, **kwargs):
                hid = "simulated-" + str(len(resets) + 1)
                resets.append(hid)
                return {"history_id": hid, "running": True}

            class FakeSocket:
                close_code = 1000
                close_reason = ""

                async def send(self, raw):
                    self.text = json.loads(raw)["text"]
                    messages.append(self.text)

                async def __aiter__(self):
                    cycle[0] += 2
                    c = cycle[0]
                    if interrupted and not self.text.startswith("Remember this partial source ledger"):
                        current = re.search(r"\[ref:([a-f0-9]{8})\]", self.text).group(1)
                        if not failed_refs:
                            failed_refs.append(current)
                            yield json.dumps({"type": "ack", "cycle": c, "text": self.text})
                            raise reactor_client.official.TimedOut("simulated accepted request timeout", [], [])
                        if len(pending_refusals) < 2:
                            retry_refs.append(current)
                            pending_refusals.append("previous_pending")
                            yield json.dumps({"type": "error", "code": "previous_pending", "forwarded": False})
                            return
                        if len(retry_refs) == 2:
                            retry_refs.append(current)
                    yield json.dumps({"type": "ack", "cycle": c, "text": self.text})
                    if self.text.startswith("Remember this partial source ledger"):
                        yield json.dumps({"type": "reply", "cycle": c + 1, "text": "OK"})
                        return
                    ref = re.search(r"\[ref:([a-f0-9]{8})\]", self.text).group(1)
                    # Real parser must discard a stale ref and a correct current
                    # ref at an ineligible cycle before accepting this answer.
                    yield json.dumps({"type": "reply", "cycle": c + 1,
                                      "text": f"# FINAL ANSWER [ref:{failed_refs[0] if failed_refs else 'ffffffff'}]: old answer [E1]"})
                    yield json.dumps({"type": "reply", "cycle": c,
                                      "text": f"# FINAL ANSWER [ref:{ref}]: WRONG [E1]"})
                    answer = ("INSUFFICIENT_EVIDENCE" if "hamster name?" in self.text else
                              "green tea [E1]" if "tea recommendation?" in self.text else "Luna 🐈 [E1]")
                    yield json.dumps({"type": "reply", "cycle": c + 1,
                                      "text": f"# FINAL ANSWER [ref:{ref}]: {answer}"})

            @asynccontextmanager
            async def connect(*args, **kwargs):
                yield FakeSocket()

            def in_process_client(cmd, **kwargs):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = reactor_client.main(cmd[2:])
                return subprocess.CompletedProcess(cmd, code, stdout.getvalue(), stderr.getvalue())

            argv = ["--questions", str(root / "questions.jsonl"), "--histories", str(root / "histories.jsonl"),
                    "--out-dir", str(root / "out"), "--method", "bm25", "--limit", "0", "--memory-mode", "targeted",
                    "--base-url", "http://127.0.0.1", "--agent-id", "fake", "--execute", "--exclusive-access",
                    "--access-window", str(root / "window.json")]
            with patch.dict("os.environ", {"REACTOR_ACCESS_KEY": "simulation-key"}), \
                 patch.object(runtime.subprocess, "run", side_effect=in_process_client), \
                 patch.object(reactor_client.official, "new_history", side_effect=reset), \
                 patch.object(reactor_client, "_connect", connect), \
                 patch.object(reactor_client.official.time, "sleep") as sleep, redirect_stdout(io.StringIO()):
                self.assertEqual(runtime.main(argv), 2 if interrupted else 0)
                if interrupted:
                    self.assertEqual(runtime.main(argv + ["--retry-timeout"]), 0)
                # A completed resume performs zero additional protocol operations.
                self.assertEqual(runtime.main(argv), 0)
            if interrupted:
                self.assertNotEqual(failed_refs[0], retry_refs[0])
                self.assertEqual(len(set(retry_refs)), 1)
                self.assertEqual([call.args[0] for call in sleep.call_args_list], [5.0, 10.0])
            predictions = runtime.read_jsonl(root / "out/predictions.jsonl")
            self.assertEqual(len(resets), 2)
            self.assertEqual(len(messages), 8 if interrupted else 5)  # preloads, questions, optional timeout/refusals
            self.assertEqual([p["citations"] for p in predictions], [["s_cat"], [], ["s_tea"]])
            self.assertEqual(predictions[0]["answer"], "Luna 🐈")
            self.assertIn("[E1] (source: s_cat, date: " + date + ")", messages[1])
            self.assertIn("user: My cat is Luna 🐈.\u2028I adopted her.", messages[1])
            self.assertIn("[session s_cat, " + date + "]", messages[0])
            self.assertEqual([p["abstain"] for p in predictions], [False, True, False])
            self.assertEqual(score.validate(predictions, {"q1", "q2", "q3"}), [])
            gold = [{"question_id": qid, "question_type": "fixture", "abstain": abstain,
                     "answer": answer, "evidence": evidence} for qid, answer, abstain, evidence in (
                         ("q1", "Luna", False, ["s_cat"]), ("q2", "unknown", True, []),
                         ("q3", "green tea", False, ["s_tea"]))]
            scored = [score.score_question(p, g) for p, g in zip(predictions, gold)]
            self.assertTrue(all(r["answer"] == "correct" for r in scored))
            self.assertEqual([r["evidence_f1"] for r in scored], [1, None, 1])
            # Fixture success proves plumbing only; no model quality is inferred.
            attempts = runtime.read_jsonl(root / "out/attempts.jsonl")
            self.assertEqual(len(attempts), 8 if interrupted else 7)
            self.assertTrue(all("client_stderr" in a["result"] for a in attempts if a["operation"] != "new_history"))
            answer_attempts = [a for a in attempts if a["operation"] == "question" and a["result"]["status"] == "answered"]
            raw = answer_attempts[0]["result"]
            self.assertEqual(json.loads(raw["client_stdout"])["answer"], "Luna 🐈 [E1]")


if __name__ == "__main__":
    unittest.main()
