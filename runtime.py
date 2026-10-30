"""Small, sequential Reactor runner. Dry run by default; never fabricates answers.

Artifacts in --out-dir: plan.json, evidence/, checkpoint.json, attempts.jsonl,
results.jsonl (successful official client lines), and predictions.jsonl.
An uncertain call stops the run rather than risking a duplicate question or reset.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from official.reactor import client as official_client
from official.reactor import predictions as adapter

ROOT = Path(__file__).resolve().parent


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def execution_lock(base_url, agent_id):
    lock_dir = ROOT / "runs/.agent-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    identity = base_url.rstrip("/").lower() + "\n" + agent_id
    path = lock_dir / (hashlib.sha256(identity.encode()).hexdigest() + ".lock")
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another runner is executing against this Reactor agent") from exc
        yield


def read_jsonl(path):
    # splitlines() also splits literal U+2028/U+0085 inside JSON strings.
    with Path(path).open(encoding="utf-8-sig") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def append_jsonl(path, value):
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def redact(value):
    """The key is only inherited by client.py; never persist it even in an error."""
    key = os.environ.get("REACTOR_ACCESS_KEY", "")
    if isinstance(value, str):
        return value.replace(key, "[REDACTED]") if key else value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def invoke(args, extra):
    cmd = [sys.executable, str(args.client), "--base-url", args.base_url,
           "--agent-id", args.agent_id, "--timeout", str(args.timeout), *extra]
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              timeout=args.timeout + 15)
        try:
            result = json.loads(proc.stdout)
            if not isinstance(result, dict):
                raise ValueError("client output is not an object")
        except ValueError:
            result = {"status": "error", "error": "client did not return a JSON object",
                      "stderr": proc.stderr[-1000:]}
        return redact(result), proc.returncode, time.monotonic() - start
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": "client process exceeded timeout"}, 3, time.monotonic() - start


def prediction(result, question, history):
    if result.get("question_id") != question["question_id"]:
        raise ValueError("client returned a different question_id")
    if result.get("status") != "answered":
        raise ValueError("no Reactor answer; refusing to invent an abstention")
    valid = {s["session_id"] for s in history["sessions"]}
    preds, skipped, notes = adapter.convert([result], {"agent"}, valid)
    if skipped or notes or len(preds) != 1:
        raise ValueError("invalid client citations or answer: " + "; ".join(skipped + notes))
    pred = preds[0]
    if not pred["abstain"] and not pred["citations"]:
        raise ValueError("answer has no valid citations")
    return pred


def validate_evidence_citations(result, evidence):
    """Reject citations not supplied in this request, even if in its history."""
    labels = {f"E{i}": e["id"] for i, e in enumerate(evidence, 1)}
    for citation in result.get("citations") or []:
        if not isinstance(citation, dict) or labels.get(citation.get("label")) != citation.get("id"):
            raise ValueError("client citation does not match the evidence sent")


def write_predictions(out, results, questions, histories, complete=False):
    by_q = {q["question_id"]: q for q in questions}
    seen, preds = set(), []
    for result in results:
        qid = result.get("question_id")
        if qid in seen or qid not in by_q:
            raise ValueError("duplicate or unknown result question_id")
        seen.add(qid)
        q = by_q[qid]
        preds.append(prediction(result, q, histories[q["history_id"]]))
    if complete and seen != set(by_q):
        raise ValueError("missing questions: " + str(sorted(set(by_q) - seen)))
    tmp = out / "predictions.jsonl.tmp"
    tmp.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in preds), encoding="utf-8")
    os.replace(tmp, out / "predictions.jsonl")
    return seen


def prepare(args):
    from retrieval import retrieve

    questions = read_jsonl(args.questions)
    if len({q["question_id"] for q in questions}) != len(questions):
        raise ValueError("duplicate question_id in questions")
    if args.question_ids:
        text = args.question_ids.read_text(encoding="utf-8")
        ids = json.loads(text) if text.lstrip().startswith("[") else text.split()
        if len(ids) != len(set(ids)) or not set(ids) <= {q["question_id"] for q in questions}:
            raise ValueError("duplicate or unknown selected question IDs")
        questions = [q for q in questions if q["question_id"] in set(ids)]
    if args.limit:
        questions = questions[:args.limit]
    # Group by dataset history without altering within-history order.
    questions.sort(key=lambda q: q["history_id"])
    selected_histories = {q["history_id"] for q in questions}
    histories = {}
    with args.histories.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                history = json.loads(line)
                if history["history_id"] in selected_histories:
                    histories[history["history_id"]] = history
    if set(histories) != selected_histories:
        raise ValueError("selected questions reference missing histories")
    passages, sizes = {}, {}
    for q in questions:
        h = histories[q["history_id"]]
        evidence = retrieve(q, h, k=args.k, method=args.method, budget=args.budget)
        valid = {s["session_id"]: s["date"] for s in h["sessions"]}
        for e in evidence:
            if e["id"] not in valid or e.get("date") != valid[e["id"]]:
                raise ValueError("retrieval returned invalid citation or date")
        date = official_client.parse_question_date(q["question_date"])
        message = official_client.build_message(q["question"], evidence, "00000000", date)
        if len(message) > args.max_chars:
            raise ValueError(f"{q['question_id']}: message {len(message)} exceeds {args.max_chars} characters")
        passages[q["question_id"]] = evidence
        sizes[q["question_id"]] = len(message)
    manifest = {
        "base_url": args.base_url, "agent_id": args.agent_id,
        "method": args.method, "k": args.k, "budget": args.budget, "max_chars": args.max_chars,
        "client_sha256": file_sha256(args.client),
        "questions_sha256": file_sha256(args.questions),
        "histories_sha256": file_sha256(args.histories),
        "question_ids": [q["question_id"] for q in questions],
        "evidence_sha256": hashlib.sha256(json.dumps(passages, sort_keys=True).encode()).hexdigest(),
        "message_chars": sizes,
    }
    return questions, histories, passages, manifest


def run(args):
    if args.limit < 0 or args.k <= 0 or args.budget <= 0 or args.timeout <= 0:
        raise ValueError("limit must be nonnegative; k, budget, and timeout must be positive")
    questions, histories, evidence, manifest = prepare(args)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    # One live runner per output directory. The server additionally enforces one
    # question at a time; operators must use only one run per team agent.
    with (out / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan_path = out / "plan.json"
        if plan_path.exists() and json.loads(plan_path.read_text()) != manifest:
            raise ValueError("run configuration/data changed; choose a new output directory")
        atomic_json(plan_path, manifest)
        evidence_dir = out / "evidence"
        evidence_dir.mkdir(exist_ok=True)
        for qid, entries in evidence.items():
            atomic_json(evidence_dir / (hashlib.sha256(qid.encode()).hexdigest() + ".json"), entries)
        state_path = out / "checkpoint.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {
            "active_dataset_history": None, "reactor_history": None, "pending": None, "completed_histories": []}
        result_path = out / "results.jsonl"
        results = read_jsonl(result_path) if result_path.exists() else []
        done = write_predictions(out, results, questions, histories)
        if state["pending"] and state["pending"].get("question_id") in done:
            state["pending"] = None  # crash after result fsync but before checkpoint
            atomic_json(state_path, state)
        remaining = [q for q in questions if q["question_id"] not in done]
        remaining_histories = list(dict.fromkeys(q["history_id"] for q in remaining))
        reset_count = len(remaining_histories) - int(bool(remaining_histories) and
            remaining_histories[0] == state["active_dataset_history"] and bool(state["reactor_history"]))
        print(json.dumps({"execute": args.execute, "credential_available": bool(os.environ.get("REACTOR_ACCESS_KEY")),
                          "question_calls": len(remaining), "history_reset_calls": reset_count,
                          "planned_api_calls": len(remaining) + reset_count,
                          "completed": len(done), "pending": state["pending"] is not None}), flush=True)
        if not args.execute:
            return 0
        if state["pending"]:
            raise ValueError("uncertain prior call recorded in checkpoint; inspect attempts.jsonl before recovery")
        if not os.environ.get("REACTOR_ACCESS_KEY"):
            raise ValueError("REACTOR_ACCESS_KEY unavailable")
        problem = official_client.environment_problem()
        if problem and args.client.resolve() == (ROOT / "official/reactor/client.py").resolve():
            raise ValueError(problem)
        for q in remaining:
            hid, qid = q["history_id"], q["question_id"]
            if hid != state["active_dataset_history"]:
                if hid in state["completed_histories"]:
                    raise ValueError("cannot return to a dataset history after resetting it")
                state["pending"] = {"operation": "new_history", "dataset_history": hid}
                atomic_json(state_path, state)
                result, exit_code, latency = invoke(args, ["--new-history"])
                append_jsonl(out / "attempts.jsonl", {"operation": "new_history", "dataset_history": hid,
                    "exit_code": exit_code, "wall_s": latency, "result": result})
                if exit_code or result.get("status") != "history" or not result.get("history_id"):
                    raise ValueError("history reset failed; execution stopped")
                if state["active_dataset_history"]:
                    state["completed_histories"].append(state["active_dataset_history"])
                state.update(active_dataset_history=hid, reactor_history=result["history_id"], pending=None)
                atomic_json(state_path, state)
            evidence_path = evidence_dir / (hashlib.sha256(qid.encode()).hexdigest() + ".json")
            extra = ["--history", state["reactor_history"], "--question", q["question"],
                     "--question-date", q["question_date"], "--question-id", qid,
                     "--max-chars", str(args.max_chars)]
            if evidence[qid]:
                extra += ["--evidence", str(evidence_path)]
            state["pending"] = {"operation": "question", "question_id": qid, "dataset_history": hid}
            atomic_json(state_path, state)
            result, exit_code, latency = invoke(args, extra)
            append_jsonl(out / "attempts.jsonl", {"operation": "question", "question_id": qid,
                "dataset_history": hid, "exit_code": exit_code, "wall_s": latency, "result": result})
            if exit_code:
                raise ValueError(f"{qid}: client failed ({result.get('status')}); execution stopped")
            if result.get("history_id") != state["reactor_history"]:
                raise ValueError("client returned an unexpected Reactor history")
            validate_evidence_citations(result, evidence[qid])
            prediction(result, q, histories[hid])
            append_jsonl(result_path, result)
            results.append(result)
            write_predictions(out, results, questions, histories)
            state["pending"] = None
            atomic_json(state_path, state)
            print(json.dumps({"question_id": qid, "status": result["status"], "wall_s": round(latency, 3)}), flush=True)
        write_predictions(out, results, questions, histories, complete=True)
        return 0


def main(argv=None):
    from retrieval import METHODS

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--histories", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--question-ids", type=Path, help="JSON array or whitespace-separated IDs")
    ap.add_argument("--limit", type=int, default=5, help="0 selects all (large batches require human approval)")
    ap.add_argument("--method", choices=METHODS, default="official")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--budget", type=int, default=12000)
    ap.add_argument("--max-chars", type=int, default=16000)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--base-url", default="https://t07.api.reactor-hackathon.rxai.dev")
    ap.add_argument("--agent-id", default="agt_0c172edd3340495a")
    ap.add_argument("--client", type=Path, default=ROOT / "official/reactor/client.py")
    ap.add_argument("--execute", action="store_true", help="make the planned API calls")
    args = ap.parse_args(argv)
    try:
        if args.execute:
            with execution_lock(args.base_url, args.agent_id):
                return run(args)
        return run(args)
    except (OSError, ValueError, KeyError) as exc:
        print("runtime error: " + redact(str(exc)), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
