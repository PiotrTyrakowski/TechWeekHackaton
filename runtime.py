"""Small, sequential Reactor runner. Dry run by default; never fabricates answers.

Artifacts in --out-dir: plan.json, evidence/, checkpoint.json, attempts.jsonl,
results.jsonl (successful official client lines), and predictions.jsonl.
An uncertain call stops the run rather than risking a duplicate question or reset.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
from pathlib import Path
import subprocess
import sys
import time
import tempfile

from official.reactor import client as official_client
from official.reactor import predictions as adapter

ROOT = Path(__file__).resolve().parent


def access_window(args, now=None):
    """Validate an operator's recorded team agreement, never a distributed lease.

    Reserve the subprocess's entire timeout before starting any remote operation.
    An already accepted request can still finish remotely after a connection loss.
    """
    if not getattr(args, "exclusive_access", False):
        raise ValueError("Reactor access is shared: coordinate exclusive use, then pass --exclusive-access")
    path = getattr(args, "access_window", None)
    if not path:
        raise ValueError("live execution requires --access-window with the mutually agreed owner, participants, and UTC interval")
    window = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(window, dict):
        raise ValueError("access window must be a JSON object")
    owner, participants = window.get("owner"), window.get("agreed_with")
    if (not isinstance(owner, str) or not owner.strip() or not isinstance(participants, list)
            or not participants or any(not isinstance(p, str) or not p.strip() for p in participants)):
        raise ValueError("access window needs owner and nonempty agreed_with participant names")
    if not isinstance(window.get("base_url"), str) or window["base_url"].rstrip("/") != args.base_url.rstrip("/") or window.get("agent_id") != args.agent_id:
        raise ValueError("access window belongs to a different Reactor agent")
    dates = []
    for field in ("starts_at", "ends_at"):
        try:
            date = datetime.fromisoformat(window[field].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError("access window dates must be timezone-aware ISO 8601 timestamps") from exc
        if date.tzinfo is None or date.utcoffset() is None:
            raise ValueError("access window dates must include a timezone")
        dates.append(date.astimezone(timezone.utc))
    start, end = dates
    now = now or datetime.now(timezone.utc)
    reserve = args.timeout + 15
    if start >= end or not start <= now < end:
        raise ValueError("exclusive access window has not started or has expired")
    if (end - now).total_seconds() < reserve:
        raise ValueError("exclusive access window cannot fit this request's timeout plus 15-second process reserve")
    # Persist only documented fields; the file is an attestation, not a secret.
    return {"owner": owner, "agreed_with": participants, "base_url": args.base_url,
            "agent_id": args.agent_id, "starts_at": start.isoformat(), "ends_at": end.isoformat()}


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def execution_lock(base_url, agent_id):
    # All local worktrees/clones of the same user share the lock. Coordination
    # with a teammate on another machine still requires an exclusive window.
    lock_dir = Path(tempfile.gettempdir()) / f"opentovibe-reactor-locks-{os.getuid()}"
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
    sync_directory(path.parent)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def append_jsonl(path, value):
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(redact(value), ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    sync_directory(Path(path).parent)


def redact(value):
    """The key is only inherited by client.py; never persist it even in an error."""
    key = os.environ.get("REACTOR_ACCESS_KEY", "")
    if isinstance(value, str):
        value = value.replace(key, "[REDACTED]") if key else value
        return re.sub(r"rxk_[A-Za-z0-9_-]+", "[REDACTED]", value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def invoke(args, extra):
    access_window(args)  # re-read before *every* reset, preload, and question
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
        if proc.stderr.strip():
            result['client_stderr'] = proc.stderr.strip()[-2000:]
        code = proc.returncode
        if code == 0 and result.get("status") not in {"history", "answered", "reply"}:
            code = 2
        return redact(result), code, time.monotonic() - start
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": "client process exceeded timeout"}, 3, time.monotonic() - start


def prediction(result, question, history):
    if result.get("question_id") != question["question_id"]:
        raise ValueError("client returned a different question_id")
    if result.get("status") != "answered":
        raise ValueError("no Reactor answer; refusing to invent an abstention")
    if not isinstance(result.get("answer"), str) or not isinstance(result.get("abstained"), bool):
        raise ValueError("client answer must be text with a boolean abstained field")
    if result["abstained"] != bool(official_client._INSUFFICIENT.match(result["answer"])):
        raise ValueError("client abstention field disagrees with its actual final answer")
    if result.get("unknown_citations"):
        raise ValueError("client answer contains evidence labels that were never supplied")
    valid = {s["session_id"] for s in history["sessions"]}
    preds, skipped, notes = adapter.convert([result], {"agent"}, valid)
    if skipped or notes or len(preds) != 1:
        raise ValueError("invalid client citations or answer: " + "; ".join(skipped + notes))
    pred = preds[0]
    # Empty citations are valid official output and must receive their actual
    # evidence score. Never borrow labels from the explanatory reply.
    return pred


def validate_evidence_citations(result, evidence):
    """Reject citations not supplied in this request, even if in its history."""
    labels = {f"E{i}": e["id"] for i, e in enumerate(evidence, 1)}
    for citation in result.get("citations") or []:
        if not isinstance(citation, dict) or labels.get(citation.get("label")) != citation.get("id"):
            raise ValueError("client citation does not match the evidence sent")
    if isinstance(result.get("answer"), str):
        cited, unknown = official_client.citations(result["answer"], evidence)
        if cited != (result.get("citations") or []) or unknown != (result.get("unknown_citations") or []):
            raise ValueError("client citation metadata disagrees with the actual marked final answer")


def write_predictions(out, results, questions, histories, complete=False, evidence=None):
    by_q = {q["question_id"]: q for q in questions}
    seen, preds = set(), []
    for result in results:
        qid = result.get("question_id")
        if qid in seen or qid not in by_q:
            raise ValueError("duplicate or unknown result question_id")
        seen.add(qid)
        q = by_q[qid]
        if evidence is not None:
            validate_evidence_citations(result, evidence[qid])
        preds.append(prediction(result, q, histories[q["history_id"]]))
    if complete and seen != set(by_q):
        raise ValueError("missing questions: " + str(sorted(set(by_q) - seen)))
    tmp = out / "predictions.jsonl.tmp"
    with tmp.open("w", encoding="utf-8") as stream:
        stream.write("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in preds))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, out / "predictions.jsonl")
    sync_directory(out)
    return seen


def prepare(args):
    from retrieval import retrieve
    message_builder = official_client.build_message
    if args.client.resolve() == (ROOT / 'reactor_client.py').resolve():
        from reactor_client import build_message
        message_builder = build_message

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
        message = message_builder(q["question"], evidence, "00000000", date)
        if len(message) > args.max_chars:
            raise ValueError(f"{q['question_id']}: message {len(message)} exceeds {args.max_chars} characters")
        passages[q["question_id"]] = evidence
        sizes[q["question_id"]] = len(message)
    manifest = {
        "base_url": args.base_url, "agent_id": args.agent_id,
        "method": args.method, "k": args.k, "budget": args.budget, "max_chars": args.max_chars,
        "timeout_s": getattr(args, "timeout", 300.0),
        "client_sha256": file_sha256(args.client),
        "source_sha256": {name: file_sha256(ROOT / name) for name in (
            "runtime.py", "official/reactor/client.py", "official/reactor/predictions.py",
            "retrieval.py", "retrieval_calibrated.py", "retrieval_dense.py", "retrieval_memory.py",
            "retrieval_reasoning.py", "retrieval_specialized.py", "models/session_selection.json",
            "models/session_selection_robust.json")},
        "questions_sha256": file_sha256(args.questions),
        "histories_sha256": file_sha256(args.histories),
        "question_ids": [q["question_id"] for q in questions],
        "evidence_sha256": hashlib.sha256(json.dumps(passages, sort_keys=True).encode()).hexdigest(),
        "message_chars": sizes,
    }
    memory = {}
    mode = getattr(args, "memory_mode", "none")
    if mode == "targeted":
        from reactor_memory import prepare_memory
        manifest["source_sha256"]["reactor_memory.py"] = file_sha256(ROOT / "reactor_memory.py")
        for hid, history in histories.items():
            memory[hid] = prepare_memory(history, [q for q in questions if q["history_id"] == hid],
                                         args.method, args.k, args.memory_budget, args.max_chars)
    manifest["memory_mode"] = mode
    manifest["memory_budget"] = getattr(args, "memory_budget", 12000)
    manifest["memory_parts"] = {hid: [{"chars": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()}
                                      for text in parts] for hid, parts in memory.items()}
    # Kept off the manifest itself: these exact strings become durable local
    # artifacts and verbatim --text requests, never benchmark predictions.
    args.prepared_memory = memory
    return questions, histories, passages, manifest


def run(args):
    if getattr(args, 'adopt_server_history', False):
        raise ValueError('History adoption is disabled: a server-reported history may belong to a teammate or another dataset user; coordinate access and start a fresh run')
    if args.limit < 0 or args.k <= 0 or args.budget <= 0 or not math.isfinite(args.timeout) or not 0 < args.timeout <= 86400:
        raise ValueError("limit must be nonnegative; k and budget positive; timeout finite, positive, and at most 86400")
    if getattr(args, "memory_budget", 12000) <= 0:
        raise ValueError("memory-budget must be positive")
    if args.execute:
        window = access_window(args)
    questions, histories, evidence, manifest = prepare(args)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    # One live runner per output directory. The server additionally enforces one
    # question at a time; operators must use only one run per team agent.
    with (out / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan_path = out / "plan.json"
        if plan_path.exists() and json.loads(plan_path.read_text()) != manifest:
            old_manifest = json.loads(plan_path.read_text())
            old_without_client = {k:v for k,v in old_manifest.items() if k != 'client_sha256'}
            new_without_client = {k:v for k,v in manifest.items() if k != 'client_sha256'}
            existing_results = out / 'results.jsonl'
            if not (getattr(args, 'upgrade_client', False) and old_without_client == new_without_client
                    and not (existing_results.exists() and existing_results.stat().st_size)):
                raise ValueError("run configuration/data changed; choose a new output directory")
            append_jsonl(out / 'client-upgrades.jsonl', {'old_manifest': old_manifest, 'new_manifest': manifest,
                         'reason': 'explicit client-only upgrade before any successful answer'})
        atomic_json(plan_path, manifest)
        evidence_dir = out / "evidence"
        evidence_dir.mkdir(exist_ok=True)
        for qid, entries in evidence.items():
            atomic_json(evidence_dir / (hashlib.sha256(qid.encode()).hexdigest() + ".json"), entries)
        for hid, parts in args.prepared_memory.items():
            atomic_json(evidence_dir / (hashlib.sha256(hid.encode()).hexdigest() + ".memory.json"), parts)
        if args.execute:
            append_jsonl(out / "access-windows.jsonl", {"window": window,
                         "recorded_at": datetime.now(timezone.utc).isoformat(),
                         "attestation_only": True})
        state_path = out / "checkpoint.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {
            "active_dataset_history": None, "reactor_history": None, "pending": None, "completed_histories": []}
        result_path = out / "results.jsonl"
        results = read_jsonl(result_path) if result_path.exists() else []
        done = write_predictions(out, results, questions, histories, evidence=evidence)
        pending = state["pending"]
        if pending and pending.get("operation") in {"new_history", "preload"}:
            attempts_path = out / "attempts.jsonl"
            attempts = read_jsonl(attempts_path) if attempts_path.exists() else []
            candidates = [a for a in attempts if pending.get("request_id") and a.get("request_id") == pending["request_id"]
                          and a.get("operation") == pending["operation"]
                          and a.get("dataset_history") == pending["dataset_history"]]
            if pending["operation"] == "preload":
                candidates = [a for a in candidates if a.get("part") == pending.get("part")]
            if candidates:
                attempt = candidates[-1]
                result = attempt.get("result", {})
                if pending["operation"] == "new_history" and attempt.get("exit_code") == 0 and result.get("status") == "history" and isinstance(result.get("history_id"), str) and result["history_id"] and result.get("running") is not False:
                    previous = state["active_dataset_history"]
                    if previous and previous != pending["dataset_history"]:
                        state["completed_histories"].append(previous)
                    state.update(active_dataset_history=pending["dataset_history"], reactor_history=result["history_id"],
                                 pending=None, memory_completed=0)
                    atomic_json(state_path, state)
                elif pending["operation"] == "preload" and attempt.get("exit_code") == 0 and result.get("status") == "reply" and isinstance(result.get("reply"), str) and result["reply"].strip() and result.get("history_id") == state["reactor_history"] and attempt.get("sha256") == pending.get("sha256"):
                    state.update(pending=None, memory_completed=pending["part"] + 1)
                    atomic_json(state_path, state)
        pending = state["pending"]
        if pending and pending.get('operation') == 'question' and pending.get('question_id') not in done:
            # A completed client response may be durable before local validation
            # or results writing. Recover only that exact successful raw attempt.
            attempts_path = out / 'attempts.jsonl'
            attempts = read_jsonl(attempts_path) if attempts_path.exists() else []
            candidates = [a for a in attempts if pending.get('request_id') and a.get('request_id') == pending['request_id']
                          and a.get('operation') == 'question'
                          and a.get('question_id') == pending['question_id']]
            if candidates:
                attempt = candidates[-1]
                result = attempt.get('result', {})
                if attempt.get('exit_code') == 0 and result.get('status') == 'answered':
                    q = next(q for q in questions if q['question_id'] == pending['question_id'])
                    if result.get('history_id') != state['reactor_history'] or q['history_id'] != pending['dataset_history']:
                        raise ValueError('durable attempt history mismatch')
                    validate_evidence_citations(result, evidence[q['question_id']])
                    prediction(result, q, histories[q['history_id']])
                    append_jsonl(result_path, result)
                    results.append(result)
                    done = write_predictions(out, results, questions, histories, evidence=evidence)
                elif args.execute and getattr(args, 'retry_closed', False) and attempt.get('exit_code') == 5 and result.get('status') == 'closed' and len([a for a in attempts if a.get('operation') == 'question' and a.get('question_id') == pending['question_id'] and a.get('result', {}).get('history_id', state['reactor_history']) == state['reactor_history']]) == 1:
                    # Organizer guide: closed may be asked again. Explicit opt-in,
                    # one retry, same history; old refs remain isolated by client.
                    append_jsonl(out / 'recovery.jsonl', {'operation': 'retry_closed',
                                 'question_id': pending['question_id'], 'history_id': state['reactor_history']})
                    state['pending'] = None
                    atomic_json(state_path, state)
                elif args.execute and getattr(args, 'restart_interrupted_history', False) and result.get('code') == 'history_changed':
                    hid = pending['dataset_history']
                    qids_in_history = {q['question_id'] for q in questions if q['history_id'] == hid}
                    recovery_path = out / 'recovery.jsonl'
                    prior = read_jsonl(recovery_path) if recovery_path.exists() else []
                    if done & qids_in_history or any(r.get('operation') == 'restart_history' and r.get('dataset_history') == hid for r in prior):
                        raise ValueError('refusing repeated restart or loss of answered history context')
                    append_jsonl(recovery_path, {'operation': 'restart_history', 'dataset_history': hid,
                                 'reason': 'server changed history before any successful question'})
                    state.update(active_dataset_history=None, reactor_history=None, pending=None)
                    atomic_json(state_path, state)
        if state["pending"] and state["pending"].get("question_id") in done:
            state["pending"] = None  # crash after result fsync but before checkpoint
            atomic_json(state_path, state)
        remaining = [q for q in questions if q["question_id"] not in done]
        remaining_histories = list(dict.fromkeys(q["history_id"] for q in remaining))
        reset_count = len(remaining_histories) - int(bool(remaining_histories) and
            remaining_histories[0] == state["active_dataset_history"] and bool(state["reactor_history"]))
        preload_count = sum(len(args.prepared_memory.get(hid, [])) -
                            (state.get("memory_completed", 0) if hid == state["active_dataset_history"] else 0)
                            for hid in remaining_histories)
        print(json.dumps({"execute": args.execute, "credential_available": bool(os.environ.get("REACTOR_ACCESS_KEY")),
                          "question_calls": len(remaining), "history_reset_calls": reset_count,
                          "preload_calls": preload_count,
                          "planned_api_calls": len(remaining) + reset_count + preload_count,
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
        completed_this_run = 0
        for q in remaining:
            hid, qid = q["history_id"], q["question_id"]
            if hid != state["active_dataset_history"]:
                if hid in state["completed_histories"]:
                    raise ValueError("cannot return to a dataset history after resetting it")
                access_window(args)
                state["pending"] = {"operation": "new_history", "dataset_history": hid, "request_id": secrets.token_hex(12)}
                atomic_json(state_path, state)
                result, exit_code, latency = invoke(args, ["--new-history"])
                append_jsonl(out / "attempts.jsonl", {"operation": "new_history", "dataset_history": hid,
                    "request_id": state["pending"]["request_id"],
                    "exit_code": exit_code, "wall_s": latency, "result": result})
                if exit_code or result.get("status") != "history" or not isinstance(result.get("history_id"), str) or not result["history_id"] or result.get("running") is False:
                    raise ValueError("history reset failed; execution stopped")
                if state["active_dataset_history"]:
                    state["completed_histories"].append(state["active_dataset_history"])
                state.update(active_dataset_history=hid, reactor_history=result["history_id"], pending=None, memory_completed=0)
                atomic_json(state_path, state)
            for index, text in enumerate(args.prepared_memory.get(hid, [])):
                if index < state.get("memory_completed", 0):
                    continue
                digest = hashlib.sha256(text.encode()).hexdigest()
                access_window(args)
                state["pending"] = {"operation": "preload", "dataset_history": hid,
                                    "part": index, "sha256": digest, "request_id": secrets.token_hex(12)}
                atomic_json(state_path, state)
                result, exit_code, latency = invoke(args, ["--history", state["reactor_history"],
                                                       "--text", text, "--max-chars", str(args.max_chars)])
                append_jsonl(out / "attempts.jsonl", {"operation": "preload", "dataset_history": hid,
                             "request_id": state["pending"]["request_id"],
                             "part": index, "sha256": digest, "exit_code": exit_code,
                             "wall_s": latency, "result": result})
                if exit_code or result.get("status") != "reply" or not isinstance(result.get("reply"), str) or not result["reply"].strip() or result.get("history_id") != state["reactor_history"]:
                    raise ValueError("memory preload failed; execution stopped")
                state.update(pending=None, memory_completed=index + 1)
                atomic_json(state_path, state)
            evidence_path = evidence_dir / (hashlib.sha256(qid.encode()).hexdigest() + ".json")
            extra = ["--history", state["reactor_history"], "--question", q["question"],
                     "--question-date", q["question_date"], "--question-id", qid,
                     "--max-chars", str(args.max_chars)]
            if evidence[qid]:
                extra += ["--evidence", str(evidence_path)]
            access_window(args)
            state["pending"] = {"operation": "question", "question_id": qid, "dataset_history": hid,
                                "request_id": secrets.token_hex(12)}
            atomic_json(state_path, state)
            result, exit_code, latency = invoke(args, extra)
            append_jsonl(out / "attempts.jsonl", {"operation": "question", "question_id": qid,
                "request_id": state["pending"]["request_id"],
                "dataset_history": hid, "exit_code": exit_code, "wall_s": latency, "result": result})
            if exit_code:
                raise ValueError(f"{qid}: client failed ({result.get('status')}); execution stopped")
            if result.get("history_id") != state["reactor_history"]:
                raise ValueError("client returned an unexpected Reactor history")
            validate_evidence_citations(result, evidence[qid])
            prediction(result, q, histories[hid])
            append_jsonl(result_path, result)
            results.append(result)
            write_predictions(out, results, questions, histories, evidence=evidence)
            state["pending"] = None
            atomic_json(state_path, state)
            print(json.dumps({"question_id": qid, "status": result["status"], "wall_s": round(latency, 3)}), flush=True)
            completed_this_run += 1
            if getattr(args, 'stop_after', 0) and completed_this_run >= args.stop_after:
                return 0
        write_predictions(out, results, questions, histories, complete=True, evidence=evidence)
        return 0


def main(argv=None):
    from retrieval import ALL_METHODS

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--histories", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--question-ids", type=Path, help="JSON array or whitespace-separated IDs")
    ap.add_argument("--limit", type=int, default=5, help="0 selects all (large batches require human approval)")
    ap.add_argument("--stop-after", type=int, default=0, help="pause after this many completed questions without changing the run manifest")
    ap.add_argument("--method", choices=ALL_METHODS, default="bm25")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--budget", type=int, default=12000)
    ap.add_argument("--max-chars", type=int, default=16000)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--base-url", default="https://t07.api.reactor-hackathon.rxai.dev")
    ap.add_argument("--agent-id", default="agt_0c172edd3340495a")
    ap.add_argument("--client", type=Path, default=ROOT / "reactor_client.py")
    ap.add_argument("--execute", action="store_true", help="make the planned API calls")
    ap.add_argument("--exclusive-access", action="store_true", help="confirm an explicitly coordinated exclusive Reactor window")
    ap.add_argument("--access-window", type=Path, help="JSON operator attestation: owner, agreed_with, starts_at, ends_at, base_url, agent_id")
    ap.add_argument("--memory-mode", choices=("none", "targeted"), default="none", help="optional source-linked shared-context preload before questions")
    ap.add_argument("--memory-budget", type=int, default=12000, help="total serialized preload characters per dataset history")
    ap.add_argument("--retry-closed", action="store_true", help="explicitly retry one previously closed request in the same history")
    ap.add_argument("--restart-interrupted-history", action="store_true", help="restart once after server history_changed, only if no question in that history succeeded")
    ap.add_argument("--upgrade-client", action="store_true", help="record a client-only upgrade before any successful answer; evidence, prompt size, and data must match")
    ap.add_argument("--adopt-server-history", action="store_true", help="deprecated and disabled: unknown server histories can contain another user's memory")
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
