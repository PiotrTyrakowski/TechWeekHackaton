"""Offline Gate 0: local protocol tests plus an unchanged historical-answer audit.

No Reactor operations or answer judging calls are made. A passed local gate does
not pass Gate 1: the preserved historical answer has no final-answer citation.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
import urllib.request
from unittest.mock import patch

from official import score
from official.reactor import client, predictions

ROOT = Path(__file__).resolve().parent
HISTORICAL = ROOT / "reports/live-smoke-20261030T2135"
HISTORICAL_FILES = ("results.jsonl", "predictions.jsonl", "completed-gold.jsonl")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


@contextmanager
def offline_only():
    """Deny real transports/processes; individual tests provide local fakes."""
    def deny(*args, **kwargs):
        raise AssertionError("Gate 0 forbids real network access and subprocess execution")

    with ExitStack() as stack:
        for obj, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                          (socket, "create_connection"), (socket, "getaddrinfo"),
                          (urllib.request, "urlopen"), (subprocess, "run"),
                          (subprocess, "Popen")):
            stack.enter_context(patch.object(obj, name, side_effect=deny))
        yield


def audit_history(archive=HISTORICAL):
    """Reparse the actual marked answer, convert it, and score without editing it."""
    archive = Path(archive)
    before = {name: sha256(archive / name) for name in HISTORICAL_FILES}
    results = read_jsonl(archive / "results.jsonl")
    stored_predictions = read_jsonl(archive / "predictions.jsonl")
    gold = read_jsonl(archive / "completed-gold.jsonl")
    if len(results) != 1 or len(stored_predictions) != 1 or len(gold) != 1:
        raise ValueError("Expected exactly one preserved completed historical answer")
    result, prediction, expected = results[0], stored_predictions[0], gold[0]
    if result["question_id"] != "q_d4ead82e5cad" or prediction["question_id"] != result["question_id"]:
        raise ValueError("Unexpected historical question scope")
    extracted = client.final_answers(result["reply"]).get(result["ref"])
    if extracted != result["answer"]:
        raise ValueError("Stored answer disagrees with raw marked final segment")
    # No original supplied-evidence file is archived here. This audit establishes
    # the historical absence of labels, not reconstructed source provenance.
    mapped, unknown = client.citations(extracted, [])
    if mapped or unknown or result.get("citations") or result.get("unknown_citations"):
        raise ValueError("Historical diagnostic was expected to have no final-segment labels")
    converted, skipped, notes = predictions.convert(results, {"agent"}, set(expected["evidence"]))
    if skipped or notes or converted != stored_predictions:
        raise ValueError("Official conversion disagrees with preserved prediction")
    errors = score.validate(stored_predictions, {expected["question_id"]})
    if errors:
        raise ValueError("Invalid historical prediction: " + "; ".join(errors))
    measured = score.score_question(prediction, expected)
    if measured["answer"] != "correct" or measured["evidence_f1"] != 0.0:
        raise ValueError("Historical correct-text/zero-citation diagnostic changed")
    after = {name: sha256(archive / name) for name in HISTORICAL_FILES}
    if before != after:
        raise ValueError("Historical files changed during read-only audit")
    return {"kind": "preserved_real_answer_not_a_new_trial", "question_id": result["question_id"],
            "actual_marked_answer": extracted, "submitted_citations": prediction["citations"],
            "official_local_result": measured, "source_sha256": before,
            "files_unchanged": True, "gate1_passed": False,
            "limitation": "Original evidence is not rehydrated; absence of final labels is verified directly. No official LLM judge was called."}


def run_tests():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    output = io.StringIO()
    with offline_only(), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    return {"kind": "local_tests_with_mocked_transports", "passed": result.wasSuccessful(),
            "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
            "skipped": len(result.skipped), "network_and_subprocess_guard": True,
            "coverage": ["current reference and eligible cycle", "marked final-segment citations",
                         "current-question label mapping and foreign-source rejection", "abstention versus transport failure",
                         "same-user sequential histories and resume", "shared-access guards and uncertain-operation recovery"],
            "log": output.getvalue()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New output directory; never overwritten")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("output already exists; preserve earlier validation artifacts")
    tests = run_tests()
    with offline_only():
        historical = audit_history()
    paths = [ROOT / "gate0_validate.py", *sorted(ROOT.glob("*.py")),
             *sorted((ROOT / "tests").glob("test_*.py")), ROOT / "official/score.py",
             ROOT / "official/reactor/client.py", ROOT / "official/reactor/predictions.py"]
    sources = {str(p.relative_to(ROOT)): sha256(p) for p in paths}
    log = tests.pop("log")
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "mode": "offline-validation-only", "gate0": "passed" if tests["passed"] else "failed",
              "new_reactor_operations": 0, "new_model_answers": 0, "official_llm_judge_calls": 0,
              "tests": tests, "historical_audit": historical, "source_sha256": sources,
              "reproduce_argv": [sys.executable, "gate0_validate.py", "--out", "runs/gate0-new-validation"],
              "remaining_gates": "Gate 1 requires a new real correct answer with a correct nonempty final citation; Gates 1–4 remain unverified and require exclusive access."}
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / "tests.log").write_text(log, encoding="utf-8")
    print(json.dumps({"gate0": report["gate0"], "tests_run": tests["tests_run"],
                      "new_reactor_operations": 0, "historical_evidence_f1": historical["official_local_result"]["evidence_f1"],
                      "gate1_passed": False, "report": str(args.out / "validation.json")}))
    return 0 if tests["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
