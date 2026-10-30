"""Compare frozen smoke_report archives without invoking Reactor or a paid judge.

Each --arm is NAME=/path/to/report.json. Repeat a name for disjoint history
archives of the same arm. Exact combined question scopes must match.
Incomplete pairs remain explicitly incomplete; no winner is selected automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from official import score


def merge_reports(reports):
    """Aggregate disjoint per-history archives; never merge predictions or retries."""
    if len(reports) == 1:
        return reports[0]
    rows = [row for report in reports for row in report["per_question"]]
    if len({r["question_id"] for r in rows}) != len(rows):
        raise ValueError("one arm contains overlapping question IDs across archives")
    completed = [r for r in rows if r["prediction"] is not None]
    measured = [r["official_local_result"] for r in completed]
    eligible = [r for r in completed if not r["gold_abstain"] and not r["prediction"]["abstain"]]
    latency = sorted(r["successful_answer_latency_s"] for r in rows
                     if isinstance(r.get("successful_answer_latency_s"), (int, float)))
    keys = ("history_reset_attempts", "question_attempts", "preload_attempts", "failed_client_invocations",
            "client_invocations", "internal_retries", "total_api_operations_observed", "total_attempt_latency_s")
    operations = {key: sum(r["operations"].get(key, 0) for r in reports) for key in keys}
    operations["client_invocation_failure_rate"] = (operations["failed_client_invocations"] / operations["client_invocations"]
                                                   if operations["client_invocations"] else None)
    operations["errors"] = [e for r in reports for e in r["operations"].get("errors", [])]
    return {"scope": {"questions": len(rows), "completed": len(completed), "missing": len(rows) - len(completed),
                      "complete": len(rows) == len(completed)},
            "completed_only_metrics": score.summarize(measured) if measured else {},
            "citation_diagnostics": {"nonabstained_answerable_completed": len(eligible),
                "final_answer_citation_coverage": sum(bool(r["citations"]) for r in eligible) / len(eligible) if eligible else None,
                "results_with_unknown_labels": sum(bool(r.get("unknown_labels")) for r in rows)},
            "successful_answer_latency_s": {"n": len(latency), "p50": statistics.median(latency) if latency else None,
                "p95": latency[math.ceil(.95 * len(latency)) - 1] if latency else None},
            "operations": operations, "per_question": rows}


def compare(arms):
    if len(arms) < 2:
        raise ValueError("need at least two named arms")
    maps = {name: {r["question_id"]: r for r in report["per_question"]} for name, report in arms.items()}
    scopes = [set(rows) for rows in maps.values()]
    if any(scope != scopes[0] for scope in scopes[1:]):
        raise ValueError("paired comparison requires identical selected question IDs")
    names = list(arms)
    reference = names[0]
    rows, deltas = [], {name: [] for name in names[1:]}
    for qid in sorted(scopes[0]):
        paired = {name: records[qid] for name, records in maps.items()}
        if len({r["question_type"] for r in paired.values()}) != 1 or len({r["gold_abstain"] for r in paired.values()}) != 1:
            raise ValueError("arms disagree about gold category or abstention")
        if len({json.dumps([r["gold_answer"], r["gold_sessions"]], sort_keys=True) for r in paired.values()}) != 1:
            raise ValueError("arms use different gold answers or sessions")
        missing = [name for name, row in paired.items() if row["prediction"] is None]
        row = {"question_id": qid, "complete_pair": not missing, "missing_arms": missing,
               "arms": {name: {key: value.get(key) for key in (
                   "status", "prediction", "official_local_result", "evidence_f1", "question_attempts",
                   "total_attempt_latency_s")} for name, value in paired.items()}}
        rows.append(row)
        if not missing and not paired[reference]["gold_abstain"]:
            for name in deltas:
                deltas[name].append(paired[name]["evidence_f1"] - paired[reference]["evidence_f1"])
    return {"reference_arm": reference, "questions": len(rows),
            "complete_pairs": sum(r["complete_pair"] for r in rows),
            "status": "complete" if all(r["complete_pair"] for r in rows) else "incomplete",
            "paired_evidence_f1_delta": {name: {"answerable_complete_pairs": len(values),
                "mean": sum(values) / len(values) if values else None} for name, values in deltas.items()},
            "arms": {name: {key: report.get(key) for key in (
                "scope", "completed_only_metrics", "citation_diagnostics", "successful_answer_latency_s", "operations")}
                for name, report in arms.items()},
            "per_question": rows,
            "interpretation": "Paired deltas use completed pairs only; incomplete runs cannot establish an overall winner. Local correct/unjudged matching is not the official LLM judge. No significance claim; histories and development reuse must be considered."}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    report_groups, hashes = {}, {}
    for arm in args.arm:
        name, path = arm.split("=", 1)
        if not name:
            raise ValueError("arm names must be nonempty")
        raw = Path(path).read_bytes()
        report_groups.setdefault(name, []).append(json.loads(raw))
        hashes.setdefault(name, []).append({"path": str(Path(path)), "sha256": hashlib.sha256(raw).hexdigest()})
    reports = {name: merge_reports(values) for name, values in report_groups.items()}
    result = compare(reports)
    result["input_report_sha256"] = hashes
    result["comparison_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite an earlier comparison silently.
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("status", "questions", "complete_pairs", "paired_evidence_f1_delta")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
