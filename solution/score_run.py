"""Score a dev run on just the questions it answered, and list the misses.

    python score_run.py runs/dev ../memory-challenge/dev/gold.jsonl
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retrieval import load_jsonl

SCORE = Path(__file__).resolve().parent.parent / "memory-challenge" / "score.py"


def main() -> int:
    run, gold_path = Path(sys.argv[1]), Path(sys.argv[2])
    preds = {p["question_id"]: p for p in load_jsonl(run / "predictions.jsonl")}
    gold = [g for g in load_jsonl(gold_path) if g["question_id"] in preds]
    subset = run / "gold-subset.jsonl"
    subset.write_text("".join(json.dumps(g) + "\n" for g in gold), encoding="utf-8")
    subprocess.run([sys.executable, str(SCORE), str(subset), str(run / "predictions.jsonl"),
                    "--details", str(run / "details.jsonl")], check=True)
    details = {d["question_id"]: d for d in load_jsonl(run / "details.jsonl")}
    results = {r["question_id"]: r for r in load_jsonl(run / "results.jsonl")}
    print("\nnot matched automatically (wrong or for the judge):")
    for g in gold:
        d, p = details[g["question_id"]], preds[g["question_id"]]
        if d["answer"] != "correct" or (d["evidence_f1"] is not None and d["evidence_f1"] < 1):
            q = results.get(g["question_id"], {}).get("retrieval", {}).get("original_question", "")
            sent = set(results.get(g["question_id"], {}).get("retrieval", {}).get("sessions", []))
            recall = len(sent & set(g["evidence"])) / len(g["evidence"]) if g["evidence"] else None
            print(f"- [{g['question_type']}] {d['answer']} f1={d['evidence_f1']} sent-recall={recall} | {q}\n"
                  f"    gold: {'ABSTAIN' if g['abstain'] else g['answer']!r}\n"
                  f"    ours: {'ABSTAIN' if p['abstain'] else p['answer']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
