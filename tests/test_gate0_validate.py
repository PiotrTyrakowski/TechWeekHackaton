"""Tests of the offline validator's safety and read-only historical boundary."""
from contextlib import asynccontextmanager, redirect_stdout, redirect_stderr
import io
import json
import re
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

import reactor_client
import runtime

import gate0_validate as gate0


class Gate0ValidationTests(unittest.TestCase):
    def test_offline_guard_rejects_transport_and_subprocess_before_execution(self):
        with gate0.offline_only():
            for call in (lambda: socket.create_connection(("example.test", 443)),
                         lambda: socket.getaddrinfo("example.test", 443),
                         lambda: urllib.request.urlopen("https://example.test"),
                         lambda: subprocess.run(["false"]),
                         lambda: subprocess.Popen(["false"])):
                with self.subTest(call=call), self.assertRaisesRegex(AssertionError, "Gate 0 forbids"):
                    call()

    def test_preserved_answer_is_scored_without_moving_narrative_citations(self):
        measured = gate0.audit_history()
        self.assertEqual(measured["actual_marked_answer"], "Luna")
        self.assertEqual(measured["submitted_citations"], [])
        self.assertEqual(measured["official_local_result"]["answer"], "correct")
        self.assertEqual(measured["official_local_result"]["evidence_f1"], 0.0)
        self.assertTrue(measured["files_unchanged"])
        self.assertFalse(measured["gate1_passed"])

    def test_same_user_remaps_e1_across_sources_and_discards_previous_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            date = "2023-05-30"
            histories = [{"history_id": "h_shared", "sessions": [
                {"session_id": "s_old", "date": date, "turns": [
                    {"role": "user", "content": "My cat is Luna."}]},
                {"session_id": "s_new", "date": date, "turns": [
                    {"role": "user", "content": "My dog is Rover."}]}]}]
            questions = [{"question_id": "q_cat", "history_id": "h_shared", "question": "Cat name?", "question_date": date},
                         {"question_id": "q_dog", "history_id": "h_shared", "question": "Dog name?", "question_date": date}]
            for name, rows in (("histories", histories), ("questions", questions)):
                (root / (name + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in rows))
            resets, refs, messages, connected_histories = [], [], [], []

            def reset(*args, **kwargs):
                resets.append("simulated-shared-history")
                return {"history_id": resets[-1], "running": True}

            class FakeSocket:
                close_code, close_reason = 1000, ""

                async def send(self, raw):
                    self.text = json.loads(raw)["text"]
                    messages.append(self.text)

                async def __aiter__(self):
                    ref = re.search(r"\[ref:([a-f0-9]{8})\]", self.text).group(1)
                    yield json.dumps({"type": "ack", "cycle": 10, "text": self.text})
                    if refs:
                        yield json.dumps({"type": "reply", "cycle": 11,
                                          "text": f"# FINAL ANSWER [ref:{refs[-1]}]: stale Luna [E1]"})
                    yield json.dumps({"type": "reply", "cycle": 10,
                                      "text": f"# FINAL ANSWER [ref:{ref}]: wrong-cycle answer [E1]"})
                    answer = "Luna" if not refs else "Rover"
                    refs.append(ref)
                    yield json.dumps({"type": "reply", "cycle": 11,
                                      "text": f"# FINAL ANSWER [ref:{ref}]: {answer} [E1]"})

            @asynccontextmanager
            async def connect(uri, *args, **kwargs):
                connected_histories.append(uri)
                yield FakeSocket()

            def in_process(cmd, **kwargs):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = reactor_client.main(cmd[2:])
                return subprocess.CompletedProcess(cmd, code, stdout.getvalue(), stderr.getvalue())

            argv = ["--questions", str(root / "questions.jsonl"), "--histories", str(root / "histories.jsonl"),
                    "--out-dir", str(root / "run"), "--limit", "0", "--k", "1", "--execute", "--exclusive-access",
                    "--agent-id", "gate0-simulation", "--base-url", "https://example.test"]
            with gate0.offline_only(), patch.dict("os.environ", {"REACTOR_ACCESS_KEY": "simulation-key"}), \
                 patch.object(runtime, "access_window", return_value={"kind": "local-simulation"}), \
                 patch.object(runtime.subprocess, "run", side_effect=in_process), \
                 patch.object(reactor_client.official, "new_history", side_effect=reset), \
                 patch.object(reactor_client, "_connect", connect), redirect_stdout(io.StringIO()):
                self.assertEqual(runtime.main(argv), 0)
            self.assertEqual(len(resets), 1)
            self.assertEqual(len(messages), 2)
            self.assertEqual(len(set(connected_histories)), 1)
            predictions = runtime.read_jsonl(root / "run/predictions.jsonl")
            self.assertEqual([(p["answer"], p["citations"]) for p in predictions],
                             [("Luna", ["s_old"]), ("Rover", ["s_new"])])
            raw = runtime.read_jsonl(root / "run/results.jsonl")
            self.assertEqual(raw[1]["late_replies"][0]["answer"], "stale Luna [E1]")
            self.assertEqual(raw[1]["citations"], [{"label": "E1", "id": "s_new"}])

    def test_changed_stored_prediction_is_rejected_instead_of_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            for name in gate0.HISTORICAL_FILES:
                shutil.copyfile(gate0.HISTORICAL / name, archive / name)
            path = archive / "predictions.jsonl"
            prediction = json.loads(path.read_text())
            prediction["citations"] = ["s_8a377a1e6a80"]
            path.write_text(json.dumps(prediction) + "\n")
            with self.assertRaisesRegex(ValueError, "conversion disagrees"):
                gate0.audit_history(archive)
            self.assertEqual(json.loads(path.read_text())["citations"], ["s_8a377a1e6a80"])


if __name__ == "__main__":
    unittest.main()
