"""Draft answers with an OpenRouter model from the evidence run.py saved, in the same message Reactor gets.

    source openrouter.env   # OPENROUTER_API_KEY
    python draft.py runs/test --split ../memory-challenge/test

Writes <run>/draft/results.jsonl in client.py's shape, so predict.py and score_run.py read it like a Reactor run.
A rerun skips drafted questions. run.py --drafts then shows each draft to Reactor, which checks it against the
evidence and gives the final answer.
"""

from __future__ import annotations

import argparse
import json
import re
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "memory-challenge" / "reactor"))
from client import INSUFFICIENT, _INSUFFICIENT, build_message, citations, final_answers, parse_question_date  # noqa: E402

from evidence import compose  # noqa: E402
from retrieval import load_jsonl  # noqa: E402

URL = "https://openrouter.ai/api/v1/chat/completions"


def complete(model: str, text: str, timeout: float = 300) -> str:
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": text}]}).encode()
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"}
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL, body, headers), timeout=timeout) as resp:
                data = json.load(resp)
            content = data["choices"][0]["message"].get("content") or ""
            if content.strip():
                return content
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429) and e.code < 500:
                raise RuntimeError(f"OpenRouter {e.code}: {e.read()[:300]!r}") from None
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError):
            pass
        time.sleep(5 * 2 ** attempt)
    raise RuntimeError("OpenRouter: no answer after 5 attempts")


def key(answer: str) -> str:
    """An answer without its labels, case, punctuation and leading articles, for counting votes."""

    words = re.sub(r"\[E\d+\]", " ", answer).lower()
    words = re.sub(r"[^\w\s]", " ", words).split()
    return " ".join(w for w in words if w not in {"a", "an", "the"})


def draft(q: dict, ev_dir: Path, model: str, samples: int = 1) -> dict:
    """The answer most of `samples` replies give (ties: the earliest), with that reply's working."""

    qid = q["question_id"]
    excerpts = json.loads((ev_dir / f"{qid}.json").read_text(encoding="utf-8"))
    info = json.loads((ev_dir / f"{qid}.info").read_text())
    passages = [{"id": e["id"], "text": e["text"], "date": e["date"]} for e in excerpts]
    ref = secrets.token_hex(4)
    text = build_message(compose(q["question"], info["kind"], info.get("table", [])), passages, ref,
                         parse_question_date(q["question_date"]))
    started = time.monotonic()
    replies, answers = [], []
    with ThreadPoolExecutor(samples) as pool:
        for reply in pool.map(lambda _: complete(model, text), range(samples)):
            answer = final_answers(reply).get(ref)
            if answer is None:  # no marker: take the reply's last line as the answer
                answer = reply.strip().splitlines()[-1].strip() if reply.strip() else INSUFFICIENT
            replies.append(reply)
            answers.append(answer)
    votes = Counter(key(a) for a in answers)
    pick = next(i for i, a in enumerate(answers) if votes[key(a)] == max(votes.values()))
    reply, answer = replies[pick], answers[pick]
    cited, unknown = citations(answer, passages)
    return {"status": "answered", "question_id": qid, "model": model, "answer": answer, "reply": reply,
            "abstained": bool(_INSUFFICIENT.match(answer)), "citations": cited, "unknown_citations": unknown,
            "latency_s": round(time.monotonic() - started, 1), "votes": dict(votes),
            "retrieval": {**info, "sessions": [e["id"] for e in excerpts], "original_question": q["question"]}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path, help="a run.py --out folder with evidence/")
    ap.add_argument("--split", type=Path, required=True)
    ap.add_argument("--model", default="deepseek/deepseek-v4.1-flash-1017")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--samples", type=int, default=1, help="replies per question; the most common answer wins")
    args = ap.parse_args()

    ev_dir = args.run / "evidence"
    out_dir = args.run / "draft"
    out_dir.mkdir(exist_ok=True)
    results_path = out_dir / "results.jsonl"
    done = {r["question_id"] for r in load_jsonl(results_path)} if results_path.exists() else set()
    todo = [q for q in load_jsonl(args.split / "questions.jsonl")
            if q["question_id"] not in done and (ev_dir / f"{q['question_id']}.info").exists()]
    print(f"{len(todo)} question(s) to draft with {args.model} ({len(done)} done)", file=sys.stderr)

    failed = 0
    with open(results_path, "a", encoding="utf-8") as out, ThreadPoolExecutor(args.workers) as pool:
        for q, fut in [(q, pool.submit(draft, q, ev_dir, args.model, args.samples)) for q in todo]:
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001 - one failed question must not stop the rest
                failed += 1
                print(f"{q['question_id']} failed: {e}", file=sys.stderr)
                continue
            out.write(json.dumps(r) + "\n")
            out.flush()
            print(f"{r['question_id']} {r['latency_s']:5.1f}s {'ABSTAIN' if r['abstained'] else ''} "
                  f"{r['answer'][:80]!r}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
