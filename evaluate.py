"""Offline retrieval diagnostics and official answer scoring; no network calls.

python evaluate.py --data data/dev --method official --method bm25 --k 4
python evaluate.py --data data/dev --predictions runs/smoke/predictions.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from official import score


def jsonl(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def partition(question_id):
    """Fixed 80/20 split, shared by dev and dev-large; never uses gold."""
    return "validation" if int(hashlib.sha256(question_id.encode()).hexdigest()[:8], 16) % 5 == 0 else "development"


def retrieval_metrics(citations, gold):
    cited, evidence = set(citations), set(gold)
    hits = len(cited & evidence)
    return {
        "recall": hits / len(evidence) if evidence else None,
        "precision": hits / len(cited) if evidence and cited else 0.0 if evidence else None,
        "evidence_f1": score.evidence_f1(cited, evidence) if evidence else None,
        "any_hit": float(bool(hits)) if evidence else None,
        "all_hit": float(evidence <= cited) if evidence else None,
    }


def summarize(records):
    result = {"n": len(records), "answerable_n": sum(not r["gold_abstain"] for r in records)}
    for name in ("recall", "precision", "evidence_f1", "any_hit", "all_hit", "latency_ms", "packed_chars", "unique_sessions"):
        values = [r[name] for r in records if r.get(name) is not None]
        result[name] = statistics.mean(values) if values else None
    times = sorted(r["latency_ms"] for r in records)
    result["latency_p95_ms"] = times[min(len(times) - 1, int(len(times) * .95))] if times else None
    return result


def revision():
    proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    return {"commit": proc.stdout.strip() if proc.returncode == 0 else None, "dirty": bool(status.stdout.strip())}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def answer_evaluation(data, predictions_path, questions, gold, output):
    predictions = list(jsonl(predictions_path))
    errors = score.validate(predictions, set(questions))
    if errors:
        raise ValueError("\n".join(errors))
    by_id = {p["question_id"]: p for p in predictions}
    by_history = defaultdict(list)
    for p in predictions:
        by_history[questions[p["question_id"]]["history_id"]].append(p)
    for history in jsonl(data / "histories.jsonl"):
        allowed = {s["session_id"] for s in history["sessions"]}
        for p in by_history.pop(history["history_id"], []):
            if set(p["citations"]) - allowed:
                raise ValueError(f"{p['question_id']}: citation outside corresponding history")
    if by_history:
        raise ValueError("Predictions reference missing dataset histories")
    # A selected questions file defines smoke-test scope. Otherwise missing predictions
    # remain wrong exactly as in score.py; do not report partial coverage as full accuracy.
    selected_gold = [gold[qid] for qid in questions]
    results = [score.score_question(by_id.get(g["question_id"]), g) for g in selected_gold]
    summary = {"scope_n": len(questions), "predictions_n": len(predictions),
               "missing_n": len(set(questions) - set(by_id)), "official_metrics": score.summarize(results),
               "limitation": "Local correct is automatic matching, not LLM-judged accuracy; unmatched answers are unjudged."}
    score.write_jsonl(output / "answer-details.jsonl", results)
    score.write_jsonl(output / "scoped-gold.jsonl", selected_gold)
    write_json(output / "answer-summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/dev"))
    parser.add_argument("--questions", type=Path, help="Optional question subset; reports its scope explicitly")
    parser.add_argument("--method", action="append")
    parser.add_argument("--k", type=int, action="append")
    parser.add_argument("--budget", type=int, default=12000)
    parser.add_argument("--out", type=Path, default=Path("experiments"))
    parser.add_argument("--predictions", type=Path, help="Score actual Reactor predictions using official score functions")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    experiment_dir = args.out / timestamp
    experiment_dir.mkdir()
    questions = {q["question_id"]: q for q in jsonl(args.questions or args.data / "questions.jsonl")}
    gold = {g["question_id"]: g for g in jsonl(args.data / "gold.jsonl")}
    if not questions or set(questions) - set(gold):
        raise ValueError("Empty question set or question missing dev gold")
    if args.predictions:
        result = answer_evaluation(args.data, args.predictions, questions, gold, experiment_dir)
        attempts_path = args.predictions.parent / "attempts.jsonl"
        attempts = list(jsonl(attempts_path)) if attempts_path.exists() else None
        result["experiment_id"] = timestamp + "-answers"
        result["git"] = revision()
        result["config"] = {"predictions": str(args.predictions), "questions": str(args.questions) if args.questions else None}
        result["dataset"] = str(args.data)
        result["reactor_call_count"] = len(attempts) if attempts is not None else None
        result["latency_s"] = sum(a.get("wall_s", 0) for a in attempts) if attempts is not None else None
        result["call_count_note"] = "Counts official-client invocations including resets; client-internal safe refusal retries excluded. None means no adjacent attempts.jsonl."
        result["failures"] = [a for a in attempts or [] if a.get("exit_code") != 0]
        result["source_sha256"] = {str(p): digest(p) for p in [Path(__file__), Path("official/score.py"), args.predictions, args.data / "gold.jsonl", args.data / "histories.jsonl"]}
        write_json(experiment_dir / "answer-summary.json", result)
        with (args.out / "registry.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    from retrieval import retrieve
    configs = [{"method": method, "k": k, "budget": args.budget}
               for method in args.method or ["official", "bm25"] for k in args.k or [4]]
    if any(c["k"] < 1 for c in configs) or args.budget < 1:
        raise ValueError("k and budget must be positive")
    records = [[] for _ in configs]
    grouped = defaultdict(list)
    for q in questions.values():
        grouped[q["history_id"]].append(q)
    started = time.perf_counter()
    for history in jsonl(args.data / "histories.jsonl"):
        qs = grouped.pop(history["history_id"], [])
        if not qs:
            continue
        allowed = {s["session_id"] for s in history["sessions"]}
        dates = {s["session_id"]: s["date"] for s in history["sessions"]}
        for q in qs:
            g = gold[q["question_id"]]
            for config, rows in zip(configs, records):
                tick = time.perf_counter()
                passages = retrieve(q, history, **config)
                latency_ms = (time.perf_counter() - tick) * 1000
                for p in passages:
                    if p["id"] not in allowed or p["date"] != dates[p["id"]]:
                        raise ValueError(f"{q['question_id']}: invalid session or date in retrieved evidence")
                ids = list(dict.fromkeys(p["id"] for p in passages))
                rows.append({"question_id": q["question_id"], "question": q["question"],
                             "history_id": q["history_id"], "question_type": g["question_type"],
                             "partition": partition(q["question_id"]), "gold_abstain": g["abstain"],
                             "retrieved_sessions": ids, "gold_sessions": g["evidence"],
                             "missing_sessions": sorted(set(g["evidence"]) - set(ids)),
                             "latency_ms": latency_ms, "packed_chars": sum(len(p["text"]) for p in passages),
                             "unique_sessions": len(ids), **retrieval_metrics(ids, g["evidence"])})
    if grouped:
        raise ValueError(f"{len(grouped)} question histories absent from histories.jsonl")
    baselines = {c["k"]: summarize(rows) for c, rows in zip(configs, records) if c["method"] == "official"}
    source_hashes = {str(p): digest(p) for p in [Path(__file__), Path("retrieval.py"), Path("official/score.py"), Path("official/reactor/examples/run_benchmark.py"), args.data / "gold.jsonl", args.data / "questions.jsonl", args.data / "histories.jsonl"]}
    reports = []
    for index, (config, rows) in enumerate(zip(configs, records)):
        baseline = baselines.get(config["k"])
        experiment_id = f"{timestamp}-{index}-{config['method']}-k{config['k']}"
        summary = summarize(rows)
        report = {"experiment_id": experiment_id, "git": revision(), "config": config,
                  "dataset": str(args.data), "split": "all", "retrieval_metrics": summary,
                  "by_type": {t: summarize([r for r in rows if r["question_type"] == t]) for t in sorted({r["question_type"] for r in rows})},
                  "by_partition": {p: summarize([r for r in rows if r["partition"] == p]) for p in ("development", "validation")},
                  "answer_metrics": None, "abstention_metrics": None, "reactor_call_count": 0,
                  "runtime_s": time.perf_counter() - started,
                  "failures": {"partial_or_missing_evidence": sum(r["all_hit"] == 0 for r in rows),
                               "zero_evidence_hit": sum(r["any_hit"] == 0 for r in rows)},
                  "improvement_vs_baseline": {name: summary[name] - baseline[name] for name in ("recall", "precision", "evidence_f1")} if baseline else None,
                  "source_sha256": source_hashes,
                  "notes": "Metrics use unique session IDs in top-k packed passages; F1 treats all retrieved sessions as citations, not Reactor-selected citations. Unanswerable excluded from evidence metrics. Dev-large shares dev questions and is not a holdout."}
        score.write_jsonl(experiment_dir / f"{index}-{config['method']}-k{config['k']}-details.jsonl", rows)
        write_json(experiment_dir / f"{index}-{config['method']}-k{config['k']}-summary.json", report)
        with (args.out / "registry.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(report, ensure_ascii=False) + "\n")
        reports.append({"experiment_id": experiment_id, "config": config, "metrics": summary,
                        "improvement_vs_baseline": report["improvement_vs_baseline"]})
    print(json.dumps({"artifacts": str(experiment_dir), "experiments": reports}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
