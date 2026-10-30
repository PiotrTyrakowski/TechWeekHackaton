"""Archive and score an observed Reactor run without modifying predictions.

python smoke_report.py --run runs/live-bm25-4-answerable \
  --questions smoke-answerable/questions.jsonl --gold smoke-answerable/gold.jsonl \
  --out reports/live-smoke
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

from official import score

ARCHIVE_FILES = ("results.jsonl", "predictions.jsonl", "attribution.jsonl", "attempts.jsonl", "plan.json", "recovery.jsonl", "checkpoint.json", "client-upgrades.jsonl", "access-windows.jsonl")


def parse_lines(raw):
    return [json.loads(line) for line in raw.decode("utf-8-sig").split('\n') if line.strip()]


def snapshot(run):
    """Read twice so a progressing run is never silently archived halfway through an append."""
    def read():
        return {name: (run / name).read_bytes() for name in ARCHIVE_FILES if (run / name).exists()}
    for _ in range(4):
        first, second = read(), read()
        if first == second:
            for name in ("results.jsonl", "predictions.jsonl", "attempts.jsonl", "recovery.jsonl"):
                if name in second:
                    parse_lines(second[name])
            return second
    raise ValueError("Run artifacts changed during snapshot; rerun report after the current write")


def build_report(questions, gold, predictions, attempts, results, checkpoint, attributions=()):
    questions = {q["question_id"]: q for q in questions}
    gold = {g["question_id"]: g for g in gold}
    if set(questions) - set(gold):
        raise ValueError("Question scope contains IDs missing from gold")
    errors = score.validate(predictions, set(questions))
    if errors:
        raise ValueError("\n".join(errors))
    by_id = {p["question_id"]: p for p in predictions}
    raw = {r.get("question_id"): r for r in results}
    attribution = {a["question_id"]: a for a in attributions}
    per_question, completed_scores = [], []
    for qid, question in questions.items():
        g, prediction = gold[qid], by_id.get(qid)
        qa = [a for a in attempts if a.get("operation") == "question" and a.get("question_id") == qid]
        measured = score.score_question(prediction, g) if prediction is not None else None
        support = set(prediction["citations"]) if prediction is not None else set()
        expected = set(g["evidence"])
        hits = len(support & expected)
        if measured:
            completed_scores.append(measured)
        status = "completed" if prediction is not None else qa[-1].get("result", {}).get("status", "unknown") if qa else "not_attempted"
        pending = checkpoint.get("pending") or {}
        per_question.append({"question_id": qid, "question": question["question"],
            "question_type": g["question_type"], "status": status,
            "pending_in_checkpoint": pending.get("question_id") == qid,
            "prediction": prediction, "gold_answer": g["answer"], "gold_abstain": g["abstain"],
            "citations": prediction["citations"] if prediction is not None else None,
            "gold_sessions": g["evidence"], "official_local_result": measured,
            "evidence_f1": measured["evidence_f1"] if measured else None,
            "evidence_precision": (hits / len(support) if support else 0.0) if measured and not g["abstain"] else None,
            "evidence_recall": (hits / len(expected) if expected else 0.0) if measured and not g["abstain"] else None,
            "unknown_labels": raw.get(qid, {}).get("unknown_citations", []),
            "attribution": attribution.get(qid),
            "reactor_supplied_evidence_f1": (score.evidence_f1(attribution[qid]["reactor_citations"], g["evidence"])
                                             if measured and not g["abstain"] and qid in attribution else None),
            "fallback_only_evidence_f1": (score.evidence_f1(attribution[qid]["fallback_citations"], g["evidence"])
                                         if measured and not g["abstain"] and qid in attribution else None),
            "question_attempts": len(qa), "total_attempt_latency_s": sum(a.get("wall_s", 0) for a in qa),
            "successful_answer_latency_s": raw.get(qid, {}).get("latency_s"),
            "manual_review": {"required": bool(measured and measured["answer"] == "unjudged"),
                              "official_judge": False,
                              "note": "Unjudged means local matching did not decide; no official LLM judge has run."}})
    retries = sum(a.get("result", {}).get("retries", 0) for a in attempts)
    errors = [{"operation": a.get("operation"), "question_id": a.get("question_id"),
               "status": a.get("result", {}).get("status"), "code": a.get("result", {}).get("code"),
               "exit_code": a.get("exit_code")} for a in attempts if a.get("exit_code") != 0]
    cited_eligible = [r for r in per_question if r["prediction"] is not None
                     and not r["gold_abstain"] and not r["prediction"]["abstain"]]
    latencies = sorted(r["successful_answer_latency_s"] for r in per_question
                       if isinstance(r["successful_answer_latency_s"], (int, float)))
    return {"created_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"questions": len(questions), "completed": len(predictions),
                  "missing": len(questions) - len(predictions),
                  "complete": len(questions) == len(predictions)},
        "completed_only_metrics": score.summarize(completed_scores) if completed_scores else {},
        "citation_diagnostics": {
            "nonabstained_answerable_completed": len(cited_eligible),
            "final_answer_citation_coverage": sum(bool(r["citations"]) for r in cited_eligible) / len(cited_eligible) if cited_eligible else None,
            "results_with_unknown_labels": sum(bool(r.get("unknown_citations")) for r in results),
            "note": "Coverage is presence of actual submitted citations, not proof of support; official Evidence F1 includes false abstentions."},
        "attribution_diagnostics": {"records": len(attribution),
            "with_reactor_citations": sum(bool(a["reactor_citations"]) for a in attribution.values()),
            "with_verified_fallback": sum(bool(a["fallback_citations"]) for a in attribution.values()),
            "with_unresolved_claims": sum(bool(a["unresolved_claims"]) for a in attribution.values()),
            "note": "Effective prediction citations and raw Reactor-supplied citations are distinct; fallback does not change Reactor answer text."},
        "successful_answer_latency_s": {"n": len(latencies),
            "p50": statistics.median(latencies) if latencies else None,
            "p95": latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
            "note": "Client answer latency, excluding retrieval, resets and preload. p95 uses nearest rank; small samples are descriptive."},
        "full_scope_note": "Metrics cover completed predictions only. Missing/pending questions are reported as incomplete, not final wrong answers.",
        "scoring_note": "Official score.py functions provide local automatic matching and evidence F1. Unmatched answers remain unjudged; this report does not run an official LLM judge.",
        "operations": {"history_reset_attempts": sum(a.get("operation") == "new_history" for a in attempts),
            "question_attempts": sum(a.get("operation") == "question" for a in attempts),
            "preload_attempts": sum(a.get("operation") == "preload" for a in attempts),
            "failed_client_invocations": len(errors),
            "client_invocation_failure_rate": len(errors) / len(attempts) if attempts else None,
            "client_invocations": len(attempts), "internal_retries": retries,
            "total_api_operations_observed": len(attempts) + retries,
            "count_note": "Observed completed client invocations plus reported internal retries; an in-flight/unlogged call cannot be counted from this snapshot.",
            "total_attempt_latency_s": sum(a.get("wall_s", 0) for a in attempts), "errors": errors},
        "per_question": per_question}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New archive directory (never overwritten)")
    args = parser.parse_args(argv)
    files = snapshot(args.run)
    files["questions.jsonl"] = args.questions.read_bytes()
    files["gold.jsonl"] = args.gold.read_bytes()
    key = os.environ.get("REACTOR_ACCESS_KEY", "").encode()
    for raw in files.values():
        if (key and key in raw) or re.search(rb"rxk_[A-Za-z0-9_-]{8,}", raw):
            raise ValueError("Refusing to archive an artifact containing credential material")
    report = build_report(parse_lines(files["questions.jsonl"]), parse_lines(files["gold.jsonl"]),
        parse_lines(files.get("predictions.jsonl", b"")), parse_lines(files.get("attempts.jsonl", b"")),
        parse_lines(files.get("results.jsonl", b"")), json.loads(files.get("checkpoint.json", b"{}")),
        parse_lines(files.get("attribution.jsonl", b"")))
    report["source_run"] = str(args.run)
    report["archive_sha256"] = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    report["report_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        (args.out / name).write_bytes(raw)
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    score.write_jsonl(args.out / "per-question.jsonl", report["per_question"])
    score.write_jsonl(args.out / "completed-gold.jsonl", [g for g in parse_lines(files["gold.jsonl"]) if g["question_id"] in {p["question_id"] for p in parse_lines(files.get("predictions.jsonl", b""))}])
    print(json.dumps({"archive": str(args.out), "scope": report["scope"], "completed_only_metrics": report["completed_only_metrics"], "operations": report["operations"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
