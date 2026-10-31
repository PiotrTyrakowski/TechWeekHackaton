"""Answer a split's questions with Reactor: retrieval -> evidence -> client.py, one Reactor history per dataset history.

    source reactor.env   # REACTOR_ACCESS_KEY, REACTOR_BASE_URL, REACTOR_AGENT_ID
    python run.py --split ../memory-challenge/test --out runs/test
    python predict.py runs/test --histories ../memory-challenge/test/histories.jsonl

Each client line goes to <out>/results.jsonl as soon as it arrives; a rerun skips answered questions. The message
sent for every question is kept in <out>/evidence/ for inspection. --dry-run builds the messages without asking.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from evidence import build, compose
from retrieval import Embedder, HistoryIndex, Reranker, SessionCache, load_histories, load_jsonl
from scan import parts

HERE = Path(__file__).resolve().parent
CLIENT = HERE.parent / "memory-challenge" / "reactor" / "client.py"
MAX_CHARS = 31000


def client(*extra: str, timeout: float) -> dict:
    cmd = [sys.executable, str(CLIENT), "--base-url", os.environ["REACTOR_BASE_URL"],
           "--agent-id", os.environ["REACTOR_AGENT_ID"], "--timeout", str(timeout), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {"status": "error", "error": (proc.stderr or proc.stdout).strip()[-500:]}


def draft_note(draft: dict, limit: int = 2500) -> str:
    """A second model's answer (from draft.py) for Reactor to check, with its working when short enough."""

    working = draft["reply"].split("# FINAL ANSWER")[0].strip()
    if len(working) > limit:
        working = working[:limit] + " ..." if limit >= 300 else ""
    lines = ["- A second reader model was given the same question and evidence. Its final answer was: "
             f"{draft['answer']}"]
    if working:
        lines.append(f"  Its working: {working}")
    lines.append("  It can be wrong. Check it against the evidence yourself: if it is right, give the same answer; "
                 "if not, give the correct one.")
    return "\n".join(lines)


def scanned(turns: list[dict], sessions: list[dict]) -> list[tuple[int, int, str]]:
    """scan.py's turns as (session index, turn, quote), each part's best first: its first turn of every part, then
    the second, ... so that a cut keeps the best of every part of the history."""

    position = {s["session_id"]: i for i, s in enumerate(sessions)}
    bounds = [p[1] for p in parts({"sessions": sessions})]
    part_of = {sid: k for k, b in enumerate(bounds) for sid in b}
    rank: dict[int, int] = {}
    keyed = []
    for t in turns:
        k = part_of.get(t["session_id"], 0)
        keyed.append(((rank.get(k, 0), k), (position[t["session_id"]], t["turn"], t["quote"])))
        rank[k] = rank.get(k, 0) + 1
    return [m for _, m in sorted(keyed, key=lambda x: x[0])]


def select(questions: list[dict], args) -> list[dict]:
    if args.qids:
        wanted = set(args.qids.split(","))
        questions = [q for q in questions if q["question_id"] in wanted]
    if args.gold and args.limit:
        gold = {g["question_id"]: g for g in load_jsonl(args.gold)}
        by_type = defaultdict(list)
        for q in questions:
            by_type[gold[q["question_id"]]["question_type"] + str(gold[q["question_id"]]["abstain"])].append(q)
        rng = random.Random(args.seed)
        picked = []
        for _, qs in sorted(by_type.items()):
            rng.shuffle(qs)
            picked += qs[: max(1, round(args.limit * len(qs) / len(questions)))]
        questions = picked
    elif args.limit:
        questions = questions[: args.limit]
    return questions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dense", default="BAAI/bge-small-en-v1.5", help="sentence-transformers model, '' for BM25 only")
    ap.add_argument("--rerank", default="cross-encoder/ms-marco-MiniLM-L-6-v2", help="cross-encoder, '' for none")
    ap.add_argument("--cache", type=Path, default=HERE / "cache")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--gold", type=Path, help="stratify --limit by question type (dev)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--qids", default="")
    ap.add_argument("--budget", type=int, default=22000, help="characters of evidence per question")
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reuse", action="store_true", help="ask with the evidence a --dry-run saved in --out")
    ap.add_argument("--drafts", type=Path, help="draft.py results.jsonl: show each question's draft to Reactor")
    ap.add_argument("--scan", type=Path, help="scan.py results.jsonl: put each question's scanned turns in its evidence")
    args = ap.parse_args()
    drafts = {r["question_id"]: r for r in load_jsonl(args.drafts)} if args.drafts else {}
    scans = {r["question_id"]: r for r in load_jsonl(args.scan)} if args.scan else {}

    questions = select(list(load_jsonl(args.split / "questions.jsonl")), args)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "evidence").mkdir(exist_ok=True)
    results_path = args.out / "results.jsonl"
    done = set()
    if results_path.exists():
        done = {r["question_id"] for r in load_jsonl(results_path) if r.get("status") == "answered"}
    groups: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        if q["question_id"] not in done:
            groups[q["history_id"]].append(q)
    todo = sum(map(len, groups.values()))
    print(f"{todo} question(s) in {len(groups)} histories to ask ({len(done)} done)", file=sys.stderr)
    if not todo:
        return 0

    histories = load_histories(args.split / "histories.jsonl", set(groups))
    embedder = cache = None
    if args.dense:
        embedder = Embedder(args.dense)
        cache = SessionCache(embedder, args.cache)
    reranker = Reranker(args.rerank) if args.rerank else None

    asked = 0
    t0 = time.time()
    with open(results_path, "a", encoding="utf-8") as out:
        for hid, qs in groups.items():
            index = None
            reactor_history = None
            for q in qs:
                ev_path = args.out / "evidence" / f"{q['question_id']}.json"
                txt_path = args.out / "evidence" / f"{q['question_id']}.txt"
                if args.reuse and ev_path.exists() and txt_path.exists():  # built by an earlier --dry-run
                    excerpts = json.loads(ev_path.read_text(encoding="utf-8"))
                    info = json.loads((args.out / "evidence" / f"{q['question_id']}.info").read_text())
                    text = compose(q["question"], info["kind"], info.get("table", []))  # today's guidance
                    budget = None
                else:
                    budget = args.budget
                while budget is not None:
                    index = index or HistoryIndex(histories[hid], cache)
                    must = scanned(scans.get(q["question_id"], {}).get("turns", []), index.sessions)
                    text, excerpts, info = build(q, index, embedder, budget=budget, reranker=reranker, must=must)
                    size = len(text) + sum(len(e["text"]) + len(e["id"]) + len(e["date"]) + 40 for e in excerpts) + 600
                    if size <= MAX_CHARS - 500 or budget < 6000:
                        break
                    budget -= max(1000, size - MAX_CHARS + 1500)
                size = len(text) + sum(len(e["text"]) + len(e["id"]) + len(e["date"]) + 40 for e in excerpts) + 600
                if q["question_id"] in drafts:  # its working shortened to what room the message has left
                    text += "\n" + draft_note(drafts[q["question_id"]], limit=min(2500, MAX_CHARS - size - 900))
                    size = len(text) + sum(len(e["text"]) + len(e["id"]) + len(e["date"]) + 40 for e in excerpts) + 600
                ev_path.write_text(json.dumps(excerpts, ensure_ascii=False, indent=1), encoding="utf-8")
                txt_path.write_text(text, encoding="utf-8")
                (args.out / "evidence" / f"{q['question_id']}.info").write_text(json.dumps(info))
                if args.dry_run:
                    print(f"{q['question_id']} {info['kind']:9s} {len(excerpts):2d} sessions ~{size} chars "
                          f"| {q['question'][:70]}", file=sys.stderr)
                    continue
                if reactor_history is None:  # one Reactor history per dataset history
                    new = client("--new-history", timeout=120)
                    if new.get("status") != "history":
                        print(f"--new-history failed: {new}", file=sys.stderr)
                        return 2
                    reactor_history = new["history_id"]
                extra = ["--history", reactor_history, "--question", text, "--question-date", q["question_date"],
                         "--question-id", q["question_id"], "--max-chars", str(MAX_CHARS)]
                if excerpts:
                    extra += ["--evidence", str(ev_path)]
                for attempt in range(2):
                    result = client(*extra, timeout=args.timeout)
                    if result.get("status") == "answered":
                        break
                    if result.get("code") == "history_changed" or result.get("status") == "closed":
                        new = client("--new-history", timeout=120)
                        reactor_history = new.get("history_id", reactor_history)
                        extra[1] = reactor_history
                result.setdefault("question_id", q["question_id"])
                result["retrieval"] = {**info, "sessions": [e["id"] for e in excerpts], "size": size,
                                       "original_question": q["question"]}
                out.write(json.dumps(result) + "\n")
                out.flush()
                asked += 1
                rate = (time.time() - t0) / asked
                print(f"[{asked}/{todo} {rate:.0f}s/q] {q['question_id']} {result.get('status')} "
                      f"{'ABSTAIN' if result.get('abstained') else ''} {str(result.get('answer', ''))[:80]!r} "
                      f"cites={[c['id'] for c in result.get('citations') or []]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
