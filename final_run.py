"""Run the final 146-question test sequentially; dry-run unless --execute.

Uses the existing runner, original question order within each user, 600s timeout,
verified attribution and one 30s startup wait after each reset. Never reads gold.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time

from evaluation_diagnostics import coverage
import runtime

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "runs/final-test-20261031")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--access-window", type=Path)
    parser.add_argument("--retry-timeout", action="store_true")
    parser.add_argument("--retry-closed", action="store_true")
    parser.add_argument("--retry-not-forwarded", action="store_true")
    args = parser.parse_args(argv)
    if args.execute and not args.access_window:
        parser.error("live execution requires an actual exclusive-access window")
    questions_path, histories_path = ROOT / "data/test/questions.jsonl", ROOT / "data/test/histories.jsonl"
    questions = runtime.read_jsonl(questions_path)
    if (len(questions) != 146 or len({q["question_id"] for q in questions}) != 146
            or len({q["history_id"] for q in questions}) != 15):
        parser.error("expected the official 146-question, 15-history test input")
    if args.execute and not os.environ.get("REACTOR_ACCESS_KEY") and (ROOT / ".env").is_file():
        name, _, value = (ROOT / ".env").read_text().strip().partition("=")
        if name != "REACTOR_ACCESS_KEY" or not value:
            parser.error("private credential file is malformed")
        os.environ[name] = value
    args.out_dir.mkdir(parents=True, exist_ok=True)
    profile = {"driver_sha256": runtime.file_sha256(Path(__file__)),
        "questions_sha256": runtime.file_sha256(questions_path),
        "histories_sha256": runtime.file_sha256(histories_path),
        "questions": 146, "histories": 15, "method": "calibrated", "k": 4,
        "timeout_s": 600, "startup_wait_s": 30, "attribution_mode": "verified", "gold_used": False}
    profile_path = args.out_dir / "launch-profile.json"
    if profile_path.exists() and json.loads(profile_path.read_text()) != profile:
        parser.error("final launch profile changed; preserve this run and choose a fresh directory")
    runtime.atomic_json(profile_path, profile)
    original_invoke, original_write = runtime.invoke, runtime.write_predictions
    original_access = runtime.access_window
    startup_path = args.out_dir / "startup-state.json"

    def access_after_startup(run_args, now=None):
        window = original_access(run_args, now)
        checkpoint_path = args.out_dir / "checkpoint.json"
        if startup_path.exists() and checkpoint_path.exists():
            startup = json.loads(startup_path.read_text())
            checkpoint = json.loads(checkpoint_path.read_text())
            if startup["history_id"] == checkpoint.get("reactor_history"):
                remaining = (datetime.fromisoformat(startup["ready_after"]) - datetime.now(timezone.utc)).total_seconds()
                if remaining > 0:
                    runtime.append_jsonl(args.out_dir / "execution-events.jsonl", {
                        "event": "startup_wait", "seconds": remaining,
                        "at": datetime.now(timezone.utc).isoformat(), "question_sent": False})
                    print(json.dumps({"event": "startup_wait", "seconds": round(remaining, 2)}), flush=True)
                    time.sleep(remaining)
                    # This check occurs before the runner journals a new question.
                    window = original_access(run_args)
        return window

    def paced_invoke(run_args, extra):
        result, code, wall = original_invoke(run_args, extra)
        if "--new-history" in extra and code == 0 and result.get("status") == "history":
            runtime.atomic_json(startup_path, {"history_id": result["history_id"],
                "ready_after": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()})
        return result, code, wall

    def write_with_progress(*positional, **keywords):
        seen = original_write(*positional, **keywords)
        predictions = runtime.read_jsonl(args.out_dir / "predictions.jsonl")
        progress = coverage(questions, predictions, expected=146)
        runtime.atomic_json(args.out_dir / "coverage.json", progress)
        print(json.dumps({"event": "test_progress", "completed": progress["completed_questions"],
            "planned": 146, "histories_complete": sum(r["completed"] == r["planned"]
                for r in progress["per_history_progress"].values()),
            "submission_coverage_valid": progress["submission_ready"]}), flush=True)
        return seen

    command = ["--questions", str(questions_path), "--histories", str(histories_path),
        "--out-dir", str(args.out_dir), "--limit", "0", "--method", "calibrated", "--k", "4",
        "--budget", "12000", "--timeout", "600", "--memory-mode", "none", "--attribution-mode", "verified"]
    if args.execute:
        command += ["--execute", "--exclusive-access", "--access-window", str(args.access_window)]
        for option in ("retry_timeout", "retry_closed", "retry_not_forwarded"):
            if getattr(args, option):
                command.append("--" + option.replace("_", "-"))
    runtime.invoke, runtime.write_predictions = paced_invoke, write_with_progress
    runtime.access_window = access_after_startup
    try:
        return runtime.main(command)
    finally:
        runtime.invoke, runtime.write_predictions = original_invoke, original_write
        runtime.access_window = original_access


if __name__ == "__main__":
    raise SystemExit(main())
