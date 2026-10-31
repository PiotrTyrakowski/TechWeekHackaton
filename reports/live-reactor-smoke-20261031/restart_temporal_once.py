"""One explicit whole-history restart for the unanswered temporal user only."""
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))
import runtime


def main():
    name, _, value = (REPO / ".env").read_text().strip().partition("=")
    if name != "REACTOR_ACCESS_KEY" or not value:
        raise ValueError("private credential unavailable")
    os.environ[name] = value
    state = json.loads((ROOT / "run/checkpoint.json").read_text())
    if state["active_dataset_history"] != "h_ffd255f5e52d":
        raise ValueError("not the unanswered temporal user")
    if any(r["question_id"] == "q_53ebfc7819cf" for r in runtime.read_jsonl(ROOT / "run/results.jsonl")):
        raise ValueError("temporal user already answered; do not reset")
    original = runtime.invoke
    wait_needed = False
    def paced(args, extra):
        nonlocal wait_needed
        if "--question" in extra and wait_needed:
            wait_needed = False
            event = {"event": "post_recovery_reset_wait", "seconds": 30,
                     "at": datetime.now(timezone.utc).isoformat(), "question_sent": False}
            runtime.append_jsonl(ROOT / "execution-events-gate2.jsonl", event)
            print(json.dumps(event), flush=True)
            time.sleep(30)
        result, code, wall = original(args, extra)
        if "--new-history" in extra and code == 0:
            wait_needed = True
        return result, code, wall
    runtime.invoke = paced
    runtime.append_jsonl(ROOT / "execution-events-gate2.jsonl", {
        "event": "explicit_temporal_history_restart_once", "at": datetime.now(timezone.utc).isoformat(),
        "basis": "Supplied support guidance: restart affected dataset history from beginning after external replacement.",
        "other_completed_answers_preserved": 7, "driver_sha256": runtime.file_sha256(Path(__file__))})
    argv = json.loads((ROOT / "command.json").read_text())["base_argv"][2:]
    return runtime.main(argv + ["--execute", "--exclusive-access", "--access-window",
        str(ROOT / "exclusive-access-gate2.json"), "--restart-interrupted-history", "--stop-after", "1"])


if __name__ == "__main__":
    raise SystemExit(main())
