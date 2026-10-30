"""Reproduce BM25/rerank literal-answer retention from the isolated dev snapshot.

Run from the repo root:
  python3 experiments/rerank-offline/audit_retention.py --data data/dev
Writes answer-retention-reproduced.json beside this script. Gold is opened only
here for evaluation; retrieval module receives question/history only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import evaluate  # noqa: E402
import retrieval  # noqa: E402
import retrieval_rerank  # noqa: E402
from official import score  # noqa: E402


def read_jsonl(path: Path):
    with path.open(encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def old_eligibility_normalize(text: str) -> str:
    """Reproduce the prior screen eligibility normalization exactly."""
    return re.sub(r"\s+", " ", " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())))


def variants(gold: dict) -> list[str]:
    raw = [gold.get("answer", ""), *(gold.get("aliases") or [])]
    excluded = {"yes", "no", "true", "false"}
    return list(dict.fromkeys(
        norm for item in raw if (norm := score.normalize(item))
        if len(norm) >= 3 and norm not in excluded
    ))


def phrase_occurs(phrase: str, text: str) -> bool:
    """Official normalization plus whole-phrase token boundaries."""
    return f" {phrase} " in f" {score.normalize(text)} "


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(data: Path) -> dict:
    questions = read_jsonl(data / "questions.jsonl")
    histories = {r["history_id"]: r for r in read_jsonl(data / "histories.jsonl")}
    gold_rows = {r["question_id"]: r for r in read_jsonl(data / "gold.jsonl")}
    counts = defaultdict(lambda: {"n": 0, "bm25": 0, "rerank": 0})
    for q in questions:
        g = gold_rows[q["question_id"]]
        if g["abstain"]:
            continue
        answers = variants(g)
        h = histories[q["history_id"]]
        sessions = {s["session_id"]: s for s in h["sessions"]}
        gold_full_text = " ".join(
            turn["content"] for sid in g["evidence"]
            for turn in sessions.get(sid, {}).get("turns", [])
        )
        # Keep the original eligibility definition: a sufficiently long answer
        # string occurs in the full gold session. Matching now uses official
        # normalization and phrase boundaries for both eligibility and retention.
        old_answers = [old_eligibility_normalize(x) for x in
                       [g.get("answer", ""), *(g.get("aliases") or [])]]
        old_answers = [a for a in old_answers if len(a) >= 3 and a not in {"yes", "no", "true", "false"}]
        old_gold_text = old_eligibility_normalize(gold_full_text)
        if not old_answers or not any(a in old_gold_text for a in old_answers):
            continue
        record = counts[evaluate.partition(q["question_id"])]
        record["n"] += 1
        for method in ("bm25", "rerank"):
            passages = (retrieval.retrieve(q, h, k=4, method="bm25", budget=12000)
                        if method == "bm25" else
                        retrieval_rerank.retrieve(q, h, k=4, budget=12000))
            # Only excerpts from gold evidence sessions count as retained.
            packed_gold_text = " ".join(
                p["text"] for p in passages if p["id"] in set(g["evidence"])
            )
            record[method] += int(any(phrase_occurs(a, packed_gold_text) for a in answers))
    total = {key: sum(row[key] for row in counts.values()) for key in ("n", "bm25", "rerank")}
    def rate(row, method):
        return row[method] / row["n"] if row["n"] else None
    return {
        "eligible_n": total["n"],
        "all": {"bm25": rate(total, "bm25"), "rerank": rate(total, "rerank")},
        "by_partition": {
            part: {"n": row["n"], "bm25": rate(row, "bm25"), "rerank": rate(row, "rerank")}
            for part, row in sorted(counts.items())
        },
        "definition": {
            "eligible": "exact prior-screen eligibility: non-abstain; at least one answer/alias NFKC+casefold token-normalized with length >=3 (excluding yes/no/true/false) occurs as a substring in concatenated full gold evidence session text",
            "retained": "at least one normalized answer/alias occurs as a whole phrase using official.score.normalize and token boundaries in retrieved text restricted to passages whose session ID is in gold evidence",
            "retrieval": "BM25 k=4 and deterministic rerank k=4, budget 12000 characters; gold is not passed to retrieval",
            "caveat": "Literal retention proxy only; the eligibility condition selects examples with an answer string present in gold-session text and this does not measure answer accuracy.",
        },
        "provenance": {
            "data": str(data),
            "source_sha256": {label: sha256(path) for label, path in (
                ("audit_retention.py", Path(__file__)),
                ("official/score.py", ROOT / "official/score.py"),
                ("retrieval.py", ROOT / "retrieval.py"),
                ("retrieval_rerank.py", Path(retrieval_rerank.__file__)),
                ("questions.jsonl", data / "questions.jsonl"),
                ("histories.jsonl", data / "histories.jsonl"),
                ("gold.jsonl", data / "gold.jsonl"))},
            "partition": "evaluate.partition SHA-256 split",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/dev")
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("answer-retention-reproduced.json"))
    args = parser.parse_args()
    result = run(args.data)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "eligible_n": result["eligible_n"], "all": result["all"], "by_partition": result["by_partition"]}, indent=2))


if __name__ == "__main__":
    main()
