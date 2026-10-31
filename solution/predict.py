"""results.jsonl (client lines, from run.py) -> predictions.jsonl for the evaluator.

    python predict.py runs/test [runs/test-recheck ...] --histories ../memory-challenge/test/histories.jsonl \
        [--questions questions.jsonl]

- answer: Reactor's final answer without its [E#] labels;
- abstain: Reactor answered INSUFFICIENT_EVIDENCE;
- citations: the sessions of the excerpts Reactor cited; when it cited none, the first-ranked session we sent.
A question with no answered line (timeout, closed...) is written as abstained, and listed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "memory-challenge" / "reactor"))
from predictions import strip_labels  # noqa: E402

from retrieval import load_jsonl  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", type=Path, nargs="+", help="run folders; a later run's answer replaces an earlier one's")
    ap.add_argument("--histories", type=Path, required=True)
    ap.add_argument("--questions", type=Path, help="write a line for every question here (missing -> abstain)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    sessions = set()
    with open(args.histories, encoding="utf-8") as f:
        for line in f:
            for s in json.loads(line)["sessions"]:
                sessions.add(s["session_id"])

    latest: dict[str, dict] = {}
    for run in args.runs:
        for r in load_jsonl(run / "results.jsonl"):
            qid = r.get("question_id")
            if qid and (r.get("status") == "answered" or qid not in latest):
                latest[qid] = r
    order = [q["question_id"] for q in load_jsonl(args.questions)] if args.questions else list(latest)

    preds, missing = [], []
    for qid in order:
        r = latest.get(qid)
        if not r or r.get("status") != "answered":
            missing.append(qid)
            preds.append({"question_id": qid, "abstain": True, "answer": "", "citations": []})
            continue
        if r.get("abstained"):
            preds.append({"question_id": qid, "abstain": True, "answer": "", "citations": []})
            continue
        cites = []
        for c in r.get("citations") or []:
            if c.get("id") in sessions and c["id"] not in cites:
                cites.append(c["id"])
        if not cites and r.get("retrieval", {}).get("top"):
            cites = [r["retrieval"]["top"]]
        answer = re.sub(r"(?:\s*[,;])+\s*$", "", re.sub(r",(?:\s*,)+", ",", strip_labels(r["answer"])))
        preds.append({"question_id": qid, "abstain": False, "answer": answer, "citations": cites})

    out = args.out or args.runs[-1] / "predictions.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for p in preds:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"{len(preds)} predictions -> {out}; {sum(p['abstain'] for p in preds)} abstained; "
          f"{len(missing)} without an answer: {missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
