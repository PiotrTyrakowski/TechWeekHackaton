"""Session-level retrieval recall on a dev split, against gold evidence.

    python eval_retrieval.py --split ../memory-challenge/dev --limit 200 --dense intfloat/multilingual-e5-base
"""

from __future__ import annotations

import argparse
import json
import re
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from retrieval import Embedder, HistoryIndex, SessionCache, load_jsonl

KS = (1, 3, 5, 8, 10)


def sample(questions, gold, limit, seed=0):
    if not limit or limit >= len(questions):
        return questions
    by_type = defaultdict(list)
    for q in questions:
        by_type[gold[q["question_id"]]["question_type"]].append(q)
    rng = random.Random(seed)
    out = []
    for qs in by_type.values():
        rng.shuffle(qs)
        out += qs[: max(1, round(limit * len(qs) / len(questions)))]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", type=Path, default=Path("../memory-challenge/dev"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dense", default="")
    ap.add_argument("--configs", default="bm25,dense,hybrid")
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    args = ap.parse_args()

    gold = {g["question_id"]: g for g in load_jsonl(args.split / "gold.jsonl")}
    questions = [q for q in load_jsonl(args.split / "questions.jsonl") if not gold[q["question_id"]]["abstain"]]
    questions = sample(questions, gold, args.limit)
    need = {q["history_id"] for q in questions}
    histories = {}
    with open(args.split / "histories.jsonl", encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\{"history_id": "([^"]+)"', line)
            if m and m.group(1) in need:
                histories[m.group(1)] = json.loads(line)
    print(f"{len(questions)} questions, {len(histories)} histories", file=sys.stderr)

    cache = embedder = None
    if args.dense:
        embedder = Embedder(args.dense)
        cache = SessionCache(embedder, args.cache)

    configs = {
        "bm25": dict(w_bm25=1.0, w_dense=0.0),
        "dense": dict(w_bm25=0.0, w_dense=1.0),
        "hybrid": dict(w_bm25=0.5, w_dense=1.0),
        "hybrid11": dict(w_bm25=1.0, w_dense=1.0),
        "hybrid03": dict(w_bm25=0.3, w_dense=1.0),
    }
    names = [c for c in args.configs.split(",") if args.dense or c == "bm25"]
    stats = {n: defaultdict(list) for n in names}
    t0 = time.time()
    for i, q in enumerate(questions):
        g = gold[q["question_id"]]
        idx = HistoryIndex(histories[q["history_id"]], cache)
        qvec = embedder.query(q["question"]) if embedder else None
        ids = [s["session_id"] for s in idx.sessions]
        ev = set(g["evidence"])
        for n in names:
            cs = idx.chunk_scores(q["question"], qvec, **configs[n])
            order = np.argsort(-idx.session_scores(cs))
            ranked = [ids[j] for j in order]
            for k in KS:
                top = set(ranked[:k])
                stats[n][("any", k)].append(bool(top & ev))
                stats[n][("all", k)].append(ev <= top)
                stats[n][(g["question_type"], k)].append(ev <= top)
        if (i + 1) % 25 == 0:
            print(f"{i + 1}/{len(questions)} {time.time() - t0:.0f}s", file=sys.stderr)

    types = sorted({gold[q["question_id"]]["question_type"] for q in questions})
    for n in names:
        print(f"== {n}")
        for row in ["any", "all", *types]:
            print(f"  {row:26s} " + " ".join(f"@{k}={np.mean(stats[n][(row, k)]):.3f}" for k in KS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
