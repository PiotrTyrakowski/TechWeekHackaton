"""One recorded recovery after an HTTP upgrade rejection, never another reset."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import runtime


def main():
    root = Path(__file__).resolve().parent
    out = root / "run"
    name, _, value = (REPO / ".env").read_text().strip().partition("=")
    if name != "REACTOR_ACCESS_KEY" or not value:
        raise ValueError("private credential unavailable")
    os.environ[name] = value
    args = argparse.Namespace(base_url="https://t07.api.reactor-hackathon.rxai.dev",
        agent_id="agt_0c172edd3340495a", client=REPO / "reactor_client.py", timeout=600,
        exclusive_access=True, access_window=root / "exclusive-access.json")
    with runtime.execution_lock(args.base_url, args.agent_id):
        runtime.access_window(args)
        state = json.loads((out / "checkpoint.json").read_text())
        pending = state["pending"]
        attempts = runtime.read_jsonl(out / "attempts.jsonl")
        previous = attempts[-1]
        if (pending["operation"] != "question" or previous["request_id"] != pending["request_id"]
                or previous["result"].get("status") != "error"
                or "refused at connect (HTTP 403)" not in previous["result"].get("error", "")):
            raise ValueError("not the recorded initial HTTP-upgrade rejection")
        probe = json.loads((root / "diagnostics/handshake-after-reset.json").read_text())
        if probe["status"] != "connected" or probe["question_sent"] or probe["history_id"] != state["reactor_history"]:
            raise ValueError("same-history readiness has not been observed")
        recovery_path = out / "recovery.jsonl"
        if recovery_path.exists():
            raise ValueError("this one-time connection recovery has already been attempted")
        manifest = json.loads((out / "plan.json").read_text())
        if not all(runtime.file_sha256(REPO / path) == digest for path, digest in manifest["source_sha256"].items()):
            raise ValueError("frozen implementation changed")
        questions = runtime.read_jsonl(root / "questions.jsonl")
        histories = {h["history_id"]: h for h in runtime.read_jsonl(root / "histories.jsonl")}
        qid = pending["question_id"]
        question = next(q for q in questions if q["question_id"] == qid)
        evidence = {q["question_id"]: json.loads((out / "evidence" /
            (hashlib.sha256(q["question_id"].encode()).hexdigest() + ".json")).read_text()) for q in questions}
        request_id = secrets.token_hex(12)
        runtime.append_jsonl(recovery_path, {"operation": "retry_connect_before_message",
            "question_id": qid, "dataset_history": question["history_id"],
            "history_id": state["reactor_history"], "previous_request_id": pending["request_id"],
            "request_id": request_id, "reset": False,
            "reason": "Initial HTTP 403 rejected WebSocket upgrade before send; same-history handshake now succeeds.",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "recovery_script_sha256": runtime.file_sha256(Path(__file__))})
        state["pending"] = {**pending, "request_id": request_id}
        runtime.atomic_json(out / "checkpoint.json", state)
        extra = ["--history", state["reactor_history"], "--question", question["question"],
            "--question-date", question["question_date"], "--question-id", qid,
            "--max-chars", "16000", "--citation-mode", "strict", "--evidence",
            str(out / "evidence" / (hashlib.sha256(qid.encode()).hexdigest() + ".json"))]
        print(json.dumps({"event": "real_same_history_question_retry", "question_id": qid,
                          "reset": False, "timeout_s": 600}), flush=True)
        result, code, wall_s = runtime.invoke(args, extra)
        runtime.append_jsonl(out / "attempts.jsonl", {"operation": "question", "question_id": qid,
            "dataset_history": question["history_id"], "request_id": request_id,
            "exit_code": code, "wall_s": wall_s, "result": result})
        if code:
            print(json.dumps(runtime.redact({"status": result.get("status"), "error": result.get("error"),
                  "code": result.get("code"), "wall_s": wall_s})), flush=True)
            return code
        if result.get("history_id") != state["reactor_history"]:
            raise ValueError("Reactor history changed; refusing result")
        runtime.validate_evidence_citations(result, evidence[qid])
        runtime.prediction(result, question, histories[question["history_id"]])
        runtime.append_jsonl(out / "results.jsonl", result)
        runtime.write_predictions(out, runtime.read_jsonl(out / "results.jsonl"), questions, histories,
                                  evidence=evidence, attribution_mode="verified")
        state["pending"] = None
        runtime.atomic_json(out / "checkpoint.json", state)
        print(json.dumps(runtime.redact({"status": result["status"], "answer": result["answer"],
              "citations": result["citations"], "latency_s": result.get("latency_s"),
              "retries": result.get("retries"), "wall_s": wall_s})), flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
