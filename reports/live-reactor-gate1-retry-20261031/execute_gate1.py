"""Explicit single Gate-1 retry with a logged 30-second post-reset startup wait."""
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
    if (ROOT / "run/attempts.jsonl").exists():
        raise ValueError("retry already attempted; preserve its state")
    now = datetime.now(timezone.utc)
    window = {"owner": "lead-wG-p1", "agreed_with": ["user: explicit instruction to try Gate 1 once again"],
        "starts_at": now.isoformat(), "ends_at": (now + timedelta(minutes=30)).isoformat(),
        "base_url": "https://t07.api.reactor-hackathon.rxai.dev", "agent_id": "agt_0c172edd3340495a",
        "authorization_basis": "User explicitly authorized one fresh retry; other-machine activity cannot be independently verified.",
        "scope": "One reset and one question, stop after one answer. No automatic larger run."}
    with (ROOT / "exclusive-access.json").open("x") as stream:
        json.dump(window, stream, indent=2)
        stream.write("\n")
    command = json.loads((ROOT / "command.json").read_text())
    original_invoke = runtime.invoke
    delayed = False

    def paced_invoke(args, extra):
        nonlocal delayed
        if "--question" in extra and not delayed:
            delayed = True
            event = {"event": "post_reset_startup_wait", "seconds": 30,
                     "started_at": datetime.now(timezone.utc).isoformat(), "question_sent": False}
            runtime.append_jsonl(ROOT / "execution-events.jsonl", event)
            print(json.dumps(event), flush=True)
            time.sleep(30)
            runtime.append_jsonl(ROOT / "execution-events.jsonl", {
                "event": "startup_wait_finished", "at": datetime.now(timezone.utc).isoformat()})
        return original_invoke(args, extra)

    runtime.invoke = paced_invoke
    runtime.atomic_json(ROOT / "execution-policy.json", {
        "driver_sha256": runtime.file_sha256(Path(__file__)), "startup_delay_seconds": 30,
        "source_files_modified": False, "started_at": now.isoformat()})
    argv = command["base_argv"][2:] + ["--stop-after", "1", "--execute", "--exclusive-access",
                                       "--access-window", str(ROOT / "exclusive-access.json")]
    print(json.dumps({"event": "starting_real_gate1_retry", "credential_available": True,
                      "initial_operations": 2, "post_reset_delay_s": 30, "timeout_s": 600}), flush=True)
    return runtime.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
