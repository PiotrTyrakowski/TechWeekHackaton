import argparse
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluate import partition
import gate_plan
import runtime


class GatePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.questions, self.histories, self.gold = [], {}, []
        serial = 0

        def add(hid, qid=None, abstain=False, category="single-session-assistant"):
            nonlocal serial
            if qid is None:
                while True:
                    serial += 1
                    qid = "q_small_gate_" + str(serial)
                    if partition(qid) == "development":
                        break
            question = {"question_id": qid, "history_id": hid,
                        "question": "What is my favorite color?", "question_date": "2023-05-30"}
            self.questions.append(question)
            self.histories[hid] = {"history_id": hid, "sessions": [{"session_id": "s_" + hid,
                "date": "2023-05-20", "turns": [{"role": "user", "content": "My favorite color is blue."}]}]}
            self.gold.append({"question_id": qid, "question_type": category, "answer": "GOLD_SECRET",
                              "abstain": abstain, "evidence": ["s_" + hid] if not abstain else []})
            return question

        self.add = add
        cat = add("h_0", gate_plan.DIAGNOSTIC_ID, category="single-session-user")
        smoke = [add("h_1", abstain=True), cat, add("h_2"),
                 add("h_3", category="multi-session"), add("h_4", category="knowledge-update")]
        for hid in ("h_pair_a", "h_pair_b", "h_pair_c"):
            add(hid)
            add(hid)
        self.smoke = smoke
        self.smoke_path = self.root / "smoke.jsonl"
        gate_plan.write_jsonl(self.smoke_path, smoke)
        self.write_inputs()
        self.args = argparse.Namespace(data=self.root, smoke=self.smoke_path,
            out_dir=self.root / "out", seed=gate_plan.SEED, memory_budget=12000,
            base_url="https://example.test", agent_id="gate-test")

    def write_inputs(self):
        for name, rows in (("questions", self.questions), ("histories", self.histories.values()), ("gold", self.gold)):
            gate_plan.write_jsonl(self.root / (name + ".jsonl"), rows)

    def offline_plan(self):
        with ExitStack() as stack:
            for obj, name in ((runtime, "run"), (runtime, "main"), (runtime, "invoke"),
                              (runtime.official_client, "new_history"), (runtime.official_client, "ask_retrying")):
                stack.enter_context(patch.object(obj, name, side_effect=AssertionError("live path invoked")))
            stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("network invoked")))
            stack.enter_context(patch("subprocess.run", side_effect=AssertionError("subprocess invoked")))
            return gate_plan.build_plan(self.args)

    def test_gate1_and_gate2_share_exact_manifest_without_repeating_cat(self):
        plan = self.offline_plan()
        gate1, gate2 = plan["gates"][1:3]
        job = plan["jobs"]["smoke-calibrated"]
        self.assertEqual(job["question_ids"][0], gate_plan.DIAGNOSTIC_ID)
        self.assertEqual(gate1["job_ids"], gate2["job_ids"])
        self.assertEqual(gate1["command_argv"][:-2], gate2["command_argv"])
        self.assertEqual(gate1["command_argv"][-2:], ["--stop-after", "1"])
        self.assertTrue(gate2["resume_same_manifest"])
        self.assertNotEqual(gate1["interim_report_command_argv"][-1], job["report_command_argv"][-1])
        self.assertEqual([g["counts"]["initial_api_operations"] for g in plan["gates"]], [0, 2, 11, 6, 4])
        self.assertEqual(job["counts"], gate_plan.counts(6, 7))
        self.assertEqual(plan["total_initial_counts_conditional_baseline_reuse"], gate_plan.counts(9, 13, 1))
        self.assertFalse(plan["exclusive_access_confirmed"])
        self.assertIsNone(plan["live_runner"])
        self.assertEqual(job["method"], "calibrated")
        self.assertEqual(plan["organizer_policy"]["external_hosted_ai_inference"], "forbidden")
        self.assertEqual(job["comparability_identity"]["timeout_s"], 600)
        for value in plan["jobs"].values():
            self.assertFalse(value["execute"])
            self.assertNotIn("--execute", value["command_argv"])
            self.assertNotIn("--access-window", value["command_argv"])

    def test_generated_commands_prepare_exact_manifests_without_protocol_calls(self):
        plan = self.offline_plan()
        commands = [plan["gates"][1]["command_argv"], plan["gates"][2]["command_argv"]]
        commands.extend(plan["jobs"][name]["command_argv"] for name in
                        ("paired-bm25", "paired-calibrated", "paired-calibrated-memory"))
        with ExitStack() as stack:
            for obj, name in ((runtime, "invoke"), (runtime.official_client, "new_history"),
                              (runtime.official_client, "ask_retrying")):
                stack.enter_context(patch.object(obj, name, side_effect=AssertionError("protocol call")))
            stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("network call")))
            stack.enter_context(patch("subprocess.run", side_effect=AssertionError("subprocess call")))
            stack.enter_context(redirect_stdout(io.StringIO()))
            for command in commands:
                self.assertEqual(runtime.main(command[2:]), 0)
        for job in plan["jobs"].values():
            expected = json.loads(Path(job["runtime_manifest"]).read_text())
            actual = json.loads((self.args.out_dir / "runs" / job["job_id"] / "plan.json").read_text())
            self.assertEqual(actual, expected)
            self.assertEqual(runtime.file_sha256(Path(job["runtime_manifest"])), job["runtime_manifest_sha256"])
            self.assertFalse((self.args.out_dir / "runs" / job["job_id"] / "attempts.jsonl").exists())

    def test_final_evidence_and_provenance_match_memory_control(self):
        plan = self.offline_plan()
        baseline, memory = (plan["jobs"][name] for name in ("paired-calibrated", "paired-calibrated-memory"))
        self.assertEqual(baseline["comparability_identity"], memory["comparability_identity"])
        self.assertEqual(baseline["per_question_evidence_sha256"], memory["per_question_evidence_sha256"])
        self.assertEqual(baseline["evidence_sha256"], memory["evidence_sha256"])
        self.assertNotEqual(baseline["runtime_manifest"], memory["runtime_manifest"])
        self.assertEqual(plan["gates"][4]["baseline_job_id"], "paired-calibrated")
        self.assertTrue(plan["comparisons"]["gate4"]["require_identical_final_evidence"])
        for path in (self.root / "out/inputs").rglob("*"):
            if path.is_file() and path.name not in ("gold.jsonl", "runtime-manifest.json"):
                self.assertNotIn("GOLD_SECRET", path.read_text())
        original_order = {q["question_id"]: i for i, q in enumerate(self.questions)}
        pair = baseline["question_ids"]
        self.assertEqual(pair, sorted(pair, key=original_order.get))
        self.assertFalse(set(pair) & set(plan["selection"]["smoke_shared_question_ids"]))

    def test_selection_excludes_whole_validation_history_and_never_uses_gold(self):
        initial = gate_plan.select_pairs(self.questions, self.smoke)
        hid = initial[0][0]["history_id"]
        validation_qid = next("q_gate_validation_" + str(i) for i in range(100)
                              if partition("q_gate_validation_" + str(i)) == "validation")
        changed = [dict(q, question_id=validation_qid) if q is initial[0][0] else q for q in self.questions]
        selected = gate_plan.select_pairs(changed, self.smoke)
        self.assertNotIn(hid, {q["history_id"] for pair in selected for q in pair})
        self.assertEqual(initial, gate_plan.select_pairs(list(self.questions), list(self.smoke)))

    def test_existing_frozen_directory_is_refused_before_writes(self):
        self.args.out_dir.mkdir()
        sentinel = self.args.out_dir / "plan.json"
        sentinel.write_text("preserve")
        with patch.object(runtime, "prepare", side_effect=AssertionError("prepare called")):
            with self.assertRaisesRegex(ValueError, "never overwritten"):
                gate_plan.build_plan(self.args)
        self.assertEqual(sentinel.read_text(), "preserve")
        self.assertEqual(list(self.args.out_dir.iterdir()), [sentinel])

    def test_cli_rejects_execute_before_creating_output(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
            gate_plan.main(["--out-dir", str(self.args.out_dir), "--execute"])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.args.out_dir.exists())


if __name__ == "__main__":
    unittest.main()
