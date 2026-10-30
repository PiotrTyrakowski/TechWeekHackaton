"""Automatic citation policy never changes Reactor text or the durable raw reply."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
import io
from unittest.mock import patch

import attribution
import runtime
import smoke_report


class RuntimeAttributionTests(unittest.TestCase):
    def fixture(self):
        question = {"question_id": "q_policy", "history_id": "h_policy",
                    "question": "What is the name of my cat?", "question_date": "2023-05-30"}
        history = {"history_id": "h_policy", "sessions": [{"session_id": "s_cat",
            "date": "2023-05-20", "turns": [{"role": "user", "content": "My cat's name is Luna."}]}]}
        evidence = [{"id": "s_cat", "date": "2023-05-20", "text": "user: My cat's name is Luna."}]
        result = {"question_id": "q_policy", "history_id": "reactor-policy", "status": "answered",
                  "answer": "Luna", "abstained": False, "citations": [], "unknown_citations": [],
                  "ref": "abcdef01", "reply": "# FINAL ANSWER [ref:abcdef01]: Luna"}
        return question, history, evidence, result

    def test_verified_policy_preserves_answer_and_writes_reproducible_separate_provenance(self):
        q, h, e, result = self.fixture()
        unchanged = copy.deepcopy(result)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            runtime.write_predictions(out, [result], [q], {h["history_id"]: h}, evidence={q["question_id"]: e},
                                      attribution_mode="verified")
            predictions = (out / "predictions.jsonl").read_bytes()
            provenance = (out / "attribution.jsonl").read_bytes()
            self.assertEqual(json.loads(predictions), {"question_id": q["question_id"], "answer": "Luna",
                                                     "abstain": False, "citations": ["s_cat"]})
            record = json.loads(provenance)
            self.assertEqual(record["reactor_citations"], [])
            self.assertEqual(record["fallback_citations"], ["s_cat"])
            self.assertEqual(record["final_citations"], ["s_cat"])
            self.assertEqual(record["raw_final_answer"], "Luna")
            runtime.write_predictions(out, [result], [q], {h["history_id"]: h}, evidence={q["question_id"]: e},
                                      attribution_mode="verified")
            self.assertEqual((out / "predictions.jsonl").read_bytes(), predictions)
            self.assertEqual((out / "attribution.jsonl").read_bytes(), provenance)
        self.assertEqual(result, unchanged)

    def test_raw_control_and_unresolved_output_keep_reactor_answer(self):
        q, h, e, result = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            runtime.write_predictions(out, [result], [q], {h["history_id"]: h}, evidence={q["question_id"]: e},
                                      attribution_mode="reactor")
            self.assertEqual(json.loads((out / "predictions.jsonl").read_text())["citations"], [])
            result["answer"] = "Whiskers"
            result["reply"] = "# FINAL ANSWER [ref:abcdef01]: Whiskers"
            runtime.write_predictions(out, [result], [q], {h["history_id"]: h}, evidence={q["question_id"]: e},
                                      attribution_mode="verified")
            self.assertEqual(json.loads((out / "predictions.jsonl").read_text())["answer"], "Whiskers")
            self.assertEqual(json.loads((out / "predictions.jsonl").read_text())["citations"], [])
            self.assertTrue(json.loads((out / "attribution.jsonl").read_text())["unresolved_claims"])

    def test_durable_answer_recovers_attribution_failure_without_another_reactor_call(self):
        q, h, e, result = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, rows in (("questions", [q]), ("histories", [h])):
                (root / (name + ".jsonl")).write_text("".join(json.dumps(row) + "\n" for row in rows))
            calls = []
            def invoke(args, extra):
                calls.append(extra)
                return ({"status": "history", "history_id": "reactor-policy", "running": True}
                        if "--new-history" in extra else result), 0, .01
            argv = ["--questions", str(root / "questions.jsonl"), "--histories", str(root / "histories.jsonl"),
                    "--out-dir", str(root / "run"), "--limit", "0", "--execute", "--exclusive-access",
                    "--base-url", "https://example.test", "--agent-id", "policy-recovery-fixture"]
            with patch.dict("os.environ", {"REACTOR_ACCESS_KEY": "simulation-key"}), \
                 patch.object(runtime, "access_window", return_value={"kind": "unit-fixture"}), \
                 patch.object(runtime, "invoke", side_effect=invoke), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with patch.object(attribution, "attribute_answer", side_effect=ValueError("attribution interrupted")):
                    self.assertEqual(runtime.main(argv), 2)
                self.assertEqual(len(calls), 2)
                self.assertEqual(runtime.main(argv), 0)
                self.assertEqual(len(calls), 2)
            out = root / "run"
            self.assertEqual(len(runtime.read_jsonl(out / "results.jsonl")), 1)
            self.assertIsNone(json.loads((out / "checkpoint.json").read_text())["pending"])
            policy = runtime.read_jsonl(out / "attribution.jsonl")
            self.assertEqual(policy[0]["fallback_citations"], ["s_cat"])
            pred = runtime.read_jsonl(out / "predictions.jsonl")
            gold = [{"question_id": q["question_id"], "question_type": "single-session-user",
                     "answer": "Luna", "abstain": False, "evidence": ["s_cat"]}]
            report = smoke_report.build_report([q], gold, pred, [], [result], {}, policy)
            self.assertEqual(report["per_question"][0]["reactor_supplied_evidence_f1"], 0)
            self.assertEqual(report["per_question"][0]["evidence_f1"], 1)
            self.assertEqual(report["attribution_diagnostics"]["with_verified_fallback"], 1)

    def test_preload_selection_cannot_look_ahead_to_later_question_topics(self):
        q, h, e, _ = self.fixture()
        dog = {"session_id": "s_dog", "date": "2023-05-20",
               "turns": [{"role": "user", "content": "My dog's name is Rover."}]}
        h["sessions"].append(dog)
        dog_evidence = [{"id": "s_dog", "date": dog["date"], "text": "user: My dog's name is Rover."}]
        later = {**q, "question_id": "q_later", "question": "What is the name of my dog?"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            histories = root / "histories.jsonl"
            histories.write_text(json.dumps(h) + "\n")
            hashes = []
            for n, topic in enumerate(("dog", "cat")):
                question_file = root / (str(n) + ".jsonl")
                question_file.write_text(json.dumps(q) + "\n" + json.dumps({**later,
                    "question": "What is the name of my " + topic + "?"}) + "\n")
                with patch("reactor_memory.retrieve", side_effect=lambda question, *a, **kw:
                           dog_evidence if "dog" in question["question"] else e), redirect_stdout(io.StringIO()):
                    self.assertEqual(runtime.main(["--questions", str(question_file), "--histories", str(histories),
                        "--out-dir", str(root / str(n)), "--limit", "0", "--memory-mode", "targeted"]), 0)
                plan = json.loads((root / str(n) / "plan.json").read_text())
                self.assertEqual(plan["memory_scope"], "first-question-prefix")
                hashes.append(plan["memory_parts"])
            self.assertEqual(hashes[0], hashes[1])
