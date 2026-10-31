"""Read every question's whole history with a long-context model and note the turns that bear on it.

    source openrouter.env   # OPENROUTER_API_KEY
    python scan.py --split ../memory-challenge/test --out runs/test

The history is cut into a few parts of whole sessions (about 100k tokens each). For each part the model gets the part
first and the question last, so the part's prefix is cached across the history's questions, and lists the turns that
help answer it as "s_<id> t<turn> | quote". Each listed turn is checked: the session must be in that part and the quote
must match the turn's text (or another turn of the same session, which then replaces it). Writes
<out>/scan/results.jsonl, one line per question with the checked turns; run.py --scan forces them into the evidence.
A rerun skips scanned questions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from draft import complete
from retrieval import load_histories, load_jsonl, tokens

PART_CHARS = 500_000
LINE = re.compile(r"(s_[0-9a-f]+)\s*[,:]?\s*t(?:urn)?\s*(\d+)\s*\|\s*(.+)")

HEADER = ("Below is part of the chat history between a user and an AI assistant: dated sessions, each turn numbered "
          "t0, t1, ... A question about the user follows the history.\n\n")
TASK = """Question (asked on {date}): {question}

List every turn in the history above that helps answer this question: the facts themselves, every item that would be
counted or summed, events whose dates matter, earlier values that a later message changed and the later ones, and what
the assistant said or recommended when the question is about that. Look through the whole history above, not just the
first match. Leave out turns about other people's things or a different item, place or event.

One line per turn, exactly in this form, at most 20 lines, best first:
s_<session id> t<turn number> | <the words in that turn that matter, copied exactly, at most 25 words>

If no turn above bears on the question, write only: NONE"""


def render(session: dict) -> str:
    lines = [f"=== Session {session['session_id']} ({session['date']}) ==="]
    lines += [f"[t{i}] {t['role']}: {t['content']}" for i, t in enumerate(session["turns"])]
    return "\n".join(lines)


def parts(history: dict, limit: int = PART_CHARS) -> list[tuple[str, dict[str, dict]]]:
    """Whole sessions in date order, cut into near-equal parts of at most about `limit` characters."""

    texts = [render(s) for s in history["sessions"]]
    n = max(1, -(-sum(map(len, texts)) // limit))
    target = sum(map(len, texts)) / n
    out, cur, size = [], [], 0
    for s, t in zip(history["sessions"], texts):
        if cur and size + len(t) > target * 1.05 and len(out) < n - 1:
            out.append(cur)
            cur, size = [], 0
        cur.append((s, t))
        size += len(t)
    out.append(cur)
    return [(HEADER + "\n\n".join(t for _, t in p), {s["session_id"]: s for s, _ in p}) for p in out]


def overlap(quote: str, text: str) -> float:
    q = set(tokens(quote))
    return len(q & set(tokens(text))) / len(q) if q else 0.0


def check(reply: str, sessions: dict[str, dict]) -> list[dict]:
    """The reply's turns that exist in this part and whose quote matches; a wrong turn number is corrected."""

    found = []
    for line in reply.splitlines():
        m = LINE.search(line.strip().strip("`*-• "))
        if not m or m.group(1) not in sessions:
            continue
        sid, ti, quote = m.group(1), int(m.group(2)), m.group(3).strip().strip('"“”')
        turns = sessions[sid]["turns"]
        best = max(range(len(turns)), key=lambda i: (overlap(quote, turns[i]["content"]), i == ti))
        if ti < len(turns) and overlap(quote, turns[ti]["content"]) >= overlap(quote, turns[best]["content"]) - 0.05:
            best = ti
        score = overlap(quote, turns[best]["content"])
        if score >= 0.6:
            found.append({"session_id": sid, "turn": best, "quote": quote, "match": round(score, 2)})
    return found


def scan(q: dict, history_parts: list[tuple[str, dict]], model: str) -> dict:
    started = time.monotonic()
    turns, replies = [], []
    for text, sessions in history_parts:
        reply = complete(model, text + "\n\n" + TASK.format(date=q["question_date"], question=q["question"]))
        replies.append(reply)
        turns += check(reply, sessions)
    seen, unique = set(), []
    for t in turns:
        if (t["session_id"], t["turn"]) not in seen:
            seen.add((t["session_id"], t["turn"]))
            unique.append(t)
    return {"question_id": q["question_id"], "model": model, "turns": unique, "replies": replies,
            "latency_s": round(time.monotonic() - started, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--qids", default="", help="comma-separated question ids (default: all)")
    ap.add_argument("--model", default="deepseek/deepseek-v4.1-flash-1017")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    out_dir = args.out / "scan"
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    done = {r["question_id"] for r in load_jsonl(results_path)} if results_path.exists() else set()
    wanted = set(args.qids.split(",")) if args.qids else None
    todo = [q for q in load_jsonl(args.split / "questions.jsonl")
            if q["question_id"] not in done and (wanted is None or q["question_id"] in wanted)]
    histories = load_histories(args.split / "histories.jsonl", {q["history_id"] for q in todo})
    history_parts = {hid: parts(h) for hid, h in histories.items()}
    print(f"{len(todo)} question(s) to scan in {len(histories)} histories "
          f"({sum(map(len, history_parts.values()))} parts) with {args.model}", file=sys.stderr)

    # The first question of each history goes alone, so the others find its parts in the provider's prompt cache.
    first, rest, seen = [], [], set()
    for q in todo:
        (rest if q["history_id"] in seen else first).append(q)
        seen.add(q["history_id"])
    failed = 0
    with open(results_path, "a", encoding="utf-8") as out, ThreadPoolExecutor(args.workers) as pool:
        for batch in (first, rest):
            for q, fut in [(q, pool.submit(scan, q, history_parts[q["history_id"]], args.model)) for q in batch]:
                try:
                    r = fut.result()
                except Exception as e:  # noqa: BLE001 - one failed question must not stop the rest
                    failed += 1
                    print(f"{q['question_id']} failed: {e}", file=sys.stderr)
                    continue
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
                out.flush()
                print(f"{r['question_id']} {r['latency_s']:5.1f}s {len(r['turns']):2d} turns "
                      f"{sorted({t['session_id'] for t in r['turns']})}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
