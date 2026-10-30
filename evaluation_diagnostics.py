"""Independent OFFLINE audit, immutable raw archive, and paired diagnostics.

Never imports the runner or calls Reactor/an LLM judge. Uses pinned official
score functions; local matching is explicitly not official Reactor accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics

from official import score
from official.reactor.client import citations as parse_citations
from official.reactor import predictions as adapter


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def unique(rows, key="question_id"):
    result = {r[key]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate " + key)
    return result


def partition(qid):
    return "validation" if int(sha(qid.encode())[:8], 16) % 5 == 0 else "development"


def ratio(n, d):
    return n / d if d else None


def latency(values):
    values = sorted(values)
    return {"n": len(values), "total_s": sum(values),
            "p50_s": statistics.median(values) if values else None,
            "p95_s": values[math.ceil(.95 * len(values)) - 1] if values else None}


def audit(root, data, large):
    q, lq = unique(lines(data / "questions.jsonl")), unique(lines(large / "questions.jsonl"))
    g, lg = unique(lines(data / "gold.jsonl")), unique(lines(large / "gold.jsonl"))
    train = {k for k in q if partition(k) == "development"}
    valid = set(q) - train
    train_histories = {q[k]["history_id"] for k in train}
    shared = sorted(k for k in valid if q[k]["history_id"] in train_histories)
    # Inspect repeated question exposure directly in tracked retrieval details.
    exposure = []
    for path in sorted((root / "experiments").rglob("*-details.jsonl")):
        rows = lines(path)
        reused = sorted({r.get("question_id") for r in rows} & valid)
        if reused:
            exposure.append({"path": str(path.relative_to(root)), "validation_n": len(reused), "sha256": sha(path.read_bytes())})
    common = set(q) & set(lq)
    gold_equal = lambda a, b: {**a, "evidence": sorted(a["evidence"])} == {**b, "evidence": sorted(b["evidence"])}
    fit = lines(root / "experiments/calibration-r2/development-fit-details.jsonl")
    fitted = {r["question_id"] for r in fit}
    retrieval = []
    leaderboard = json.loads((root / "experiments/maximum-score-r2/leaderboard.json").read_text())
    for entry in leaderboard["leaderboard"]:
        if entry["name"] not in {"BM25-4", "calibrated-4"}:
            continue
        detail = root / entry["artifact"].replace("-summary.json", "-details.jsonl")
        records = unique(lines(detail))
        scopes = {"all": set(records), "validation": valid & set(records), "unseen_history_validation": valid - set(shared)}
        metrics = {}
        for name, ids in scopes.items():
            rows = [records[k] for k in ids if k in records]
            answerable = [r for r in rows if not r["gold_abstain"]]
            f1s = [score.evidence_f1(r["retrieved_sessions"], r["gold_sessions"]) for r in answerable]
            metrics[name] = {"n": len(rows), "answerable_n": len(answerable),
                             "retrieval_proxy_f1": statistics.mean(f1s) if f1s else None,
                             "mean_evidence_text_chars": statistics.mean(r["packed_chars"] for r in rows) if rows else None}
        retrieval.append({"dataset": entry["dataset"], "method": entry["name"], "detail_sha256": sha(detail.read_bytes()),
                          "metrics": metrics,
                          "leaderboard_f1_matches_recomputed": math.isclose(metrics["all"]["retrieval_proxy_f1"], entry["metrics"]["evidence_f1"], abs_tol=1e-12)})
    return {"kind": "measured-local-artifact-audit", "reactor_operations": 0,
        "source_sha256": {str(p): sha(p.read_bytes()) for p in [data / "questions.jsonl", large / "questions.jsonl", data / "gold.jsonl", large / "gold.jsonl", root / "models/session_selection.json", root / "official/score.py"]},
        "dev": {"questions": len(q), "answerable": sum(not v["abstain"] for v in g.values()),
                "histories": len({v["history_id"] for v in q.values()}),
                "history_question_counts": dict(Counter(Counter(v["history_id"] for v in q.values()).values())),
                "question_types": dict(Counter(v["question_type"] for v in g.values())),
                "development_n": len(train), "validation_n": len(valid),
                "recorded_fit_ids": len(fitted), "recorded_fit_matches_development": fitted == train,
                "validation_shared_training_history_ids": shared,
                "validation_unseen_history_n": len(valid) - len(shared),
                "validation_unseen_history_answerable_n": sum(not g[k]["abstain"] for k in valid - set(shared))},
        "dev_large": {"questions": len(lq), "same_question_ids": set(q) == set(lq),
                "matching_question_text_n": sum(q[k]["question"] == lq[k]["question"] for k in common),
                "changed_question_dates_n": sum(q[k]["question_date"] != lq[k]["question_date"] for k in common),
                "matching_gold_including_evidence_sets_n": sum(gold_equal(g[k], lg[k]) for k in common)},
        "validation_exposure_artifacts": exposure,
        "retrieval_recomputed": retrieval,
        "interpretation": "Exposure is measured; the amount of adaptive selection bias is unknown. Shared histories are a leakage risk, not proof of answer-text leakage. Retrieval F1 uses retrieved sessions as hypothetical citations, never Reactor accuracy."}


def load_snapshot(run):
    """Include original evidence/preloads, which the older reporter omits."""
    names = ("attempts.jsonl", "results.jsonl", "predictions.jsonl", "plan.json", "checkpoint.json",
             "recovery.jsonl", "access-windows.jsonl", "client-upgrades.jsonl")
    def read():
        paths = [run / n for n in names if (run / n).exists()]
        paths += sorted((run / "evidence").glob("*.json"))
        return {str(p.relative_to(run)): p.read_bytes() for p in paths}
    first, second = read(), read()
    if first != second:
        raise ValueError("Run changed during snapshot; wait until settled")
    return second


def build_report(files, questions, gold):
    qmap, gmap = unique(questions), unique(gold)
    if set(qmap) - set(gmap):
        raise ValueError("Missing gold")
    def rows(name):
        return [json.loads(x) for x in files.get(name, b"").decode("utf-8-sig").splitlines() if x.strip()]
    predictions, attempts, results = rows("predictions.jsonl"), rows("attempts.jsonl"), rows("results.jsonl")
    errors = score.validate(predictions, set(qmap))
    if errors:
        raise ValueError("; ".join(errors))
    pmap, rmap = unique(predictions), unique(results)
    if set(rmap) - set(qmap) or any(a.get("question_id") not in qmap for a in attempts if a.get("operation") == "question"):
        raise ValueError("Raw result/attempt outside question scope")
    plan = json.loads(files.get("plan.json", b"{}"))
    checkpoint = json.loads(files.get("checkpoint.json", b"{}"))
    active, history_ids, isolation = None, [], []
    for a in attempts:
        r = a.get("result", {})
        if a.get("operation") == "new_history" and a.get("exit_code") == 0 and r.get("status") == "history":
            active = (a.get("dataset_history"), r.get("history_id"))
            history_ids.append(r.get("history_id"))
        elif a.get("operation") in {"question", "preload"}:
            if not active or (a.get("dataset_history"), r.get("history_id")) != active:
                isolation.append({"question_id": a.get("question_id"), "issue": "request cannot be tied to this run's last successful reset"})
    per_question, completed_scores, full_scores = [], [], []
    positions = Counter()
    for qid, q in qmap.items():
        g, p = gmap[qid], pmap.get(qid)
        positions[q["history_id"]] += 1
        qa = [a for a in attempts if a.get("operation") == "question" and a.get("question_id") == qid]
        ep = "evidence/" + sha(qid.encode()) + ".json"
        evidence = json.loads(files[ep]) if ep in files else None
        invalid, unverifiable = [], []
        observed = [a.get("result", {}) for a in qa]
        if qid in rmap:
            observed.append(rmap[qid])
        for r in observed:
            if r.get("unknown_citations"):
                invalid.append("unknown_label")
            if r.get("status") == "answered":
                if evidence is None:
                    unverifiable.append("missing_original_evidence")
                else:
                    cited, unknown = parse_citations(r.get("answer", ""), evidence)
                    if unknown or cited != r.get("citations", []) or unknown != r.get("unknown_citations", []):
                        invalid.append("final_segment_mapping_mismatch")
        if evidence is not None and p and set(p["citations"]) - {e["id"] for e in evidence}:
            invalid.append("prediction_citation_outside_current_evidence")
        measured = score.score_question(p, g) if p is not None else None
        full_scores.append(score.score_question(p, g))
        if measured:
            completed_scores.append(measured)
        raw_answered = any(r.get("status") == "answered" for r in observed)
        converted, skipped, notes = adapter.convert([rmap[qid]], {"agent"}) if qid in rmap else ([], [], [])
        provenance = "verified" if p is not None and converted == [p] and not skipped and not notes else (
            "no_prediction" if p is None else "missing_raw_result_or_conversion_mismatch")
        per_question.append({"question_id": qid, "question_record": q, "sequence_position": positions[q["history_id"]],
            "gold_record": g, "prediction": p, "official_local_result": measured,
            "prediction_provenance": provenance,
            "raw_response_completed": raw_answered, "valid_prediction_completed": p is not None,
            "attempted": bool(qa), "invalid_citation_reasons": sorted(set(invalid)),
            "citation_validation_unknown": sorted(set(unverifiable)),
            "evidence": evidence, "evidence_sha256": sha(files[ep]) if ep in files else None,
            "evidence_chars": sum(len(e["text"]) for e in evidence) if evidence is not None else None,
            "question_attempt_latency": latency([a["wall_s"] for a in qa if isinstance(a.get("wall_s"), (float, int))]),
            "successful_answer_latency_s": rmap.get(qid, {}).get("latency_s"),
            "failure_codes": [a.get("result", {}).get("code", a.get("result", {}).get("status")) for a in qa if a.get("exit_code") != 0]})
    completed_summary = score.summarize(completed_scores) if completed_scores else {}
    counts = Counter(r["answer"] for r in completed_scores)
    attempted = sum(r["attempted"] for r in per_question)
    invalid_n = sum(bool(r["invalid_citation_reasons"]) for r in per_question)
    retries = sum(a.get("result", {}).get("retries", 0) for a in attempts)
    pending = checkpoint.get("pending")
    pending_logged = bool(pending and pending.get("request_id") and any(a.get("request_id") == pending["request_id"] for a in attempts))
    return {"kind": "offline-official-local-scoring", "official_llm_judge_run": False,
        "scorer_sha256": sha(Path(score.__file__).read_bytes()),
        "adapter_sha256": sha(Path(adapter.__file__).read_bytes()), "plan": plan,
        "scope": {"planned": len(qmap), "valid_predictions": len(pmap), "missing": len(qmap) - len(pmap),
            "raw_responses_completed": sum(r["raw_response_completed"] for r in per_question),
            "response_completion_rate": ratio(sum(r["raw_response_completed"] for r in per_question), len(qmap)),
            "valid_prediction_completion_rate": ratio(len(pmap), len(qmap))},
        "actual_prediction_outcomes_local": {"correct": counts["correct"], "wrong": counts["wrong"], "unjudged": counts["unjudged"],
            "note": "Unjudged requires independent review. Automatic matching is not official Reactor accuracy."},
        "completed_only_official_local": completed_summary,
        "full_scope_official_submission": score.summarize(full_scores) if full_scores else {},
        "full_scope_note": "Exact official missing-prediction behavior; missing counts here are submission penalties, not observed model wrong answers. Completed-only evidence excludes transport missingness; full-scope evidence includes it.",
        "citations": {"invalid_question_n": invalid_n, "attempted_question_n": attempted,
            "invalid_question_rate": None if any(r["citation_validation_unknown"] for r in per_question) else ratio(invalid_n, attempted),
            "invalid_question_rate_lower_bound": ratio(invalid_n, attempted),
            "unverifiable_question_n": sum(bool(r["citation_validation_unknown"]) for r in per_question),
            "note": "Question incidence, including rejected raw attempts; not label precision. Missing archival evidence remains unknown."},
        "operations": {"invocations": len(attempts), "by_operation": dict(Counter(a.get("operation") for a in attempts)),
            "internal_retries": retries, "observed_api_operations": len(attempts) + retries,
            "failed_invocations": sum(a.get("exit_code") != 0 for a in attempts),
            "failure_codes": dict(Counter(a.get("result", {}).get("code", a.get("result", {}).get("status", "unknown")) for a in attempts if a.get("exit_code") != 0)),
            "pending": pending, "pending_has_durable_attempt": pending_logged,
            "unlogged_pending_operation_possible": bool(pending and not pending_logged),
            "note": "Observed lower bound if pending/unlogged calls exist; retries count requests, not necessarily forwarded model turns."},
        "latency_by_operation": {op: latency([a["wall_s"] for a in attempts if a.get("operation") == op and isinstance(a.get("wall_s"), (float, int))]) for op in sorted({a["operation"] for a in attempts})},
        "isolation": {"reset_history_ids": history_ids, "issues": isolation,
            "note": "Local reset lineage cannot exclude external concurrent access; requires exclusive-access evidence."},
        "per_question": per_question}


def compare(arms):
    if len(arms) != 2:
        raise ValueError("Compare exactly two arms per hypothesis")
    (left_name, left), (right_name, right) = arms.items()
    maps = [unique(r["per_question"]) for r in (left, right)]
    if set(maps[0]) != set(maps[1]):
        raise ValueError("Different question scopes")
    issues = []
    for field in ("scorer_sha256", "adapter_sha256"):
        if not left.get(field) or left.get(field) != right.get(field):
            issues.append("Missing or different " + field)
    if set(left["isolation"]["reset_history_ids"]) & set(right["isolation"]["reset_history_ids"]):
        issues.append("Reactor history reused between configurations")
    for name, report in arms.items():
        if report["isolation"]["issues"] or not report["isolation"]["reset_history_ids"]:
            issues.append(name + ": reset lineage incomplete or violated")
        if report["scope"]["missing"] or report["operations"]["pending"]:
            issues.append(name + ": incomplete or pending")
        if any(r["prediction_provenance"] not in {"verified", "no_prediction"} for r in report["per_question"]):
            issues.append(name + ": unverified prediction conversion")
    for field in ("budget", "max_chars", "timeout_s", "client_sha256"):
        if left["plan"].get(field) != right["plan"].get(field):
            issues.append("Different " + field + "; explain as a declared treatment or rerun")
    pairs, f1_deltas, outcomes = [], [], Counter()
    for qid in maps[0]:
        a, b = maps[0][qid], maps[1][qid]
        if a["question_record"] != b["question_record"]:
            raise ValueError("Different question text/history/date: " + qid)
        if a["sequence_position"] != b["sequence_position"]:
            raise ValueError("Different within-user question order: " + qid)
        ga, gb = a["gold_record"], b["gold_record"]
        if {**ga, "evidence": sorted(ga["evidence"])} != {**gb, "evidence": sorted(gb["evidence"])}:
            raise ValueError("Different gold: " + qid)
        complete = all(r["prediction"] is not None for r in (a, b))
        delta = None
        if complete:
            sa, sb = a["official_local_result"], b["official_local_result"]
            outcomes[sa["answer"] + " -> " + sb["answer"]] += 1
            if not ga["abstain"]:
                delta = sb["evidence_f1"] - sa["evidence_f1"]
                f1_deltas.append(delta)
        pairs.append({"question_id": qid, "history_id": a["question_record"]["history_id"],
            "sequence_position": a["sequence_position"], "complete_pair": complete,
            "evidence_f1_delta": delta, "evidence_changed": a["evidence_sha256"] != b["evidence_sha256"],
            "arms": {left_name: a, right_name: b}})
    return {"reference": left_name, "candidate": right_name, "validity_issues": issues,
        "paired_answerable_completed_n": len(f1_deltas), "paired_actual_citation_f1_delta": statistics.mean(f1_deltas) if f1_deltas else None,
        "local_answer_transitions": dict(outcomes), "per_question": pairs,
        "interpretation": "Descriptive paired diagnostic only. Unjudged transitions do not establish answer wins/losses; incomplete or confounded trials cannot establish a winner. Bootstrap by history for a later frozen confirmation, not by duplicated dev/dev-large question."}


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def coverage(questions, predictions, expected=146):
    """Gold-free final coverage/progress validation; never fills missing answers."""
    qmap = unique(questions)
    errors = score.validate(predictions, set(qmap))
    if len(qmap) != expected:
        errors.append(f"Expected {expected} questions, found {len(qmap)}")
    completed = {p.get("question_id") for p in predictions if isinstance(p, dict)} & set(qmap)
    histories = {}
    for qid, q in qmap.items():
        row = histories.setdefault(q["history_id"], {"planned": 0, "completed": 0, "missing_ids": []})
        row["planned"] += 1
        row["completed"] += qid in completed
        if qid not in completed:
            row["missing_ids"].append(qid)
    return {"expected_questions": expected, "planned_questions": len(qmap), "completed_questions": len(completed),
            "missing_ids": sorted(set(qmap) - completed), "format_errors": errors,
            "submission_ready": not errors and len(completed) == expected,
            "per_history_progress": histories, "gold_used": False,
            "note": "Coverage only, not answer quality or execution permission. Never fabricate abstentions for missing/API-failed answers; never reset on timeout."}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    a.add_argument("--data", type=Path, required=True)
    a.add_argument("--large", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    for name in ("run", "questions", "gold", "out"):
        r.add_argument("--" + name, type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("--arm", action="append", required=True, help="NAME=report.json (exactly two)")
    c.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("coverage")
    for name in ("questions", "predictions", "out"):
        v.add_argument("--" + name, type=Path, required=True)
    v.add_argument("--expected", type=int, default=146)
    args = ap.parse_args(argv)
    if args.command == "audit":
        result = audit(args.root, args.data, args.large)
    elif args.command == "coverage":
        result = coverage(lines(args.questions), lines(args.predictions), args.expected)
    elif args.command == "report":
        files = load_snapshot(args.run)
        if "questions.jsonl" in files or "gold.jsonl" in files:
            raise ValueError("Reserved archive names")
        files.update({"questions.jsonl": args.questions.read_bytes(), "gold.jsonl": args.gold.read_bytes()})
        key = os.environ.get("REACTOR_ACCESS_KEY", "").encode()
        if any((key and key in raw) or re.search(rb"rxk_[A-Za-z0-9_-]{8,}", raw) for raw in files.values()):
            raise ValueError("Refusing to archive credentials")
        result = build_report(files, lines(args.questions), lines(args.gold))
        result["archive_sha256"] = {name: sha(raw) for name, raw in files.items()}
        result["diagnostics_sha256"] = sha(Path(__file__).read_bytes())
        args.out.mkdir(parents=True, exist_ok=False)
        for name, raw in files.items():
            target = args.out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        write_new(args.out / "report.json", result)
        return 0
    else:
        arms, hashes = {}, {}
        for value in args.arm:
            name, path = value.split("=", 1)
            if not name or name in arms:
                raise ValueError("Distinct nonempty arm names required")
            raw = Path(path).read_bytes()
            arms[name] = json.loads(raw)
            hashes[name] = sha(raw)
        result = compare(arms)
        result["input_sha256"] = hashes
    result["diagnostics_sha256"] = sha(Path(__file__).read_bytes())
    write_new(args.out, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
