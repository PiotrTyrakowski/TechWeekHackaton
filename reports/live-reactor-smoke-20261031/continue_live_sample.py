"""Continue the frozen eight-question live sample; no parallel requests."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))
import runtime


def main():
    name, _, value = (REPO / ".env").read_text().strip().partition("=")
    if name != "REACTOR_ACCESS_KEY" or not value:
        raise ValueError("private credential unavailable")
    os.environ[name] = value
    checkpoint = json.loads((ROOT / "run/checkpoint.json").read_text())
    if checkpoint["pending"]:
        raise ValueError("pending operation requires explicit recovery")
    now = datetime.now(timezone.utc)
    window = {"owner": "lead-wG-p1", "agreed_with": ["user: explicit instruction to continue real benchmark samples"],
        "starts_at": now.isoformat(), "ends_at": (now + timedelta(minutes=45)).isoformat(),
        "base_url": "https://t07.api.reactor-hackathon.rxai.dev", "agent_id": "agt_0c172edd3340495a",
        "authorization_basis": "Latest user instruction to continue actual benchmark evaluation. Other-machine activity is not independently observable.",
        "scope": "Finish the frozen eight-question development sample only; no automatic full test."}
    with (ROOT / "exclusive-access-gate2.json").open("x") as stream:
        json.dump(window, stream, indent=2)
        stream.write("\n")
    original_invoke = runtime.invoke
    needs_startup_wait = False

    def paced_invoke(args, extra):
        nonlocal needs_startup_wait
        if "--question" in extra and needs_startup_wait:
            needs_startup_wait = False
            event = {"event": "post_reset_startup_wait", "seconds": 30,
                     "started_at": datetime.now(timezone.utc).isoformat(), "question_sent": False}
            runtime.append_jsonl(ROOT / "execution-events-gate2.jsonl", event)
            print(json.dumps(event), flush=True)
            time.sleep(30)
        result, code, wall = original_invoke(args, extra)
        if "--new-history" in extra and code == 0 and result.get("status") == "history":
            needs_startup_wait = True
        return result, code, wall

    runtime.invoke = paced_invoke
    runtime.atomic_json(ROOT / "execution-policy-gate2.json", {
        "driver_sha256": runtime.file_sha256(Path(__file__)), "startup_delay_after_each_reset_seconds": 30,
        "same_user_questions_reset": False, "source_files_modified": False, "started_at": now.isoformat()})
    command = json.loads((ROOT / "command.json").read_text())["base_argv"][2:]
    print(json.dumps({"event": "continuing_real_eight_question_sample", "completed_before": 1,
        "remaining_questions": 7, "remaining_resets": 6, "initial_remaining_operations": 13}), flush=True)
    return runtime.main(command + ["--execute", "--exclusive-access", "--access-window",
                                   str(ROOT / "exclusive-access-gate2.json")])


if __name__ == "__main__":
    raise SystemExit(main())
