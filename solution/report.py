"""Every Reactor call our runs made, with checks that each response is a valid answer to the question we sent.

    python report.py [--out reactor_report.md]

Reads runs/*/results.jsonl (one client.py line per Reactor call) and writes a Markdown report and the same rows as
JSON (reactor_calls.json). Checks per call:
- answered: client status "answered";
- ref: the reply's final-answer line carries this question's ref, so it answers this message and not another one;
- citations: every cited label is one we sent and names a session of that history;
- cited: an answer (not an abstention) cites at least one excerpt;
- size: the message we sent was within the 31,000-character limit;
- abstention: abstained exactly when the answer is INSUFFICIENT_EVIDENCE.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

from draft import key
from retrieval import load_jsonl

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "memory-challenge"
MAX_CHARS = 31000
CHECKS = ["answered", "ref", "citations", "cited", "size", "abstention"]
SUBMISSION = ["test", "test2"]  # the runs predict.py reads for predictions.jsonl, in that order
DRAFT = re.compile(r"A second reader model .*? Its final answer was: (.*)")


def sessions_of(split: str) -> set[str]:
    out = set()
    with open(DATA / split / "histories.jsonl", encoding="utf-8") as f:
        for line in f:
            out.update(re.findall(r'"session_id": "([^"]+)"', line))
    return out


def check(r: dict, sessions: set[str]) -> dict[str, bool]:
    answered = r.get("status") == "answered"
    answer = r.get("answer") or ""
    size = (r.get("retrieval") or {}).get("size")
    return {
        "answered": answered,
        "ref": answered and f"[ref:{r.get('ref')}]" in (r.get("reply") or ""),
        "citations": answered and not r.get("unknown_citations") and all(c.get("id") in sessions
                                                                         for c in r.get("citations") or []),
        "cited": answered and (r.get("abstained") or bool(r.get("citations"))),
        "size": size is None or size <= MAX_CHARS,
        "abstention": answered and bool(r.get("abstained")) == answer.strip().startswith("INSUFFICIENT_EVIDENCE"),
    }


def rows_of(run: Path, test_qids: set[str], sessions: dict[str, set[str]], gold: dict) -> list[dict]:
    rows = []
    for i, r in enumerate(load_jsonl(run / "results.jsonl"), 1):
        split = "test" if r.get("question_id") in test_qids else "dev"
        retrieval = r.get("retrieval") or {}
        m = DRAFT.search(r.get("question") or "")
        draft = m.group(1).strip() if m else None
        answer = r.get("answer") or ""
        rows.append({
            "run": run.name, "split": split, "n": i, "question_id": r.get("question_id"),
            "question": retrieval.get("original_question") or (r.get("question") or "").split("\n\n")[0],
            "status": r.get("status"), "answer": answer, "abstained": bool(r.get("abstained")),
            "citations": [c.get("id") for c in r.get("citations") or []],
            "latency_s": r.get("latency_s"), "retries": r.get("retries", 0),
            "late_replies": len(r.get("late_replies") or []), "size": retrieval.get("size"),
            "draft": draft, "agrees_with_draft": None if draft is None else key(answer) == key(draft),
            "gold": gold.get(r.get("question_id")), "checks": check(r, sessions[split]), "error": r.get("error"),
        })
    return rows


def flat(row: dict) -> dict:
    """One call as a flat row (for the JSON file and the dashboard): checks as columns, citations as text."""

    failed = [c for c in CHECKS if not row["checks"][c]]
    out = {"id": f"{row['run']}#{row['n']}", "purpose": "submission" if row["run"] in SUBMISSION else "testing"}
    out.update({k: v for k, v in row.items() if k not in ("checks", "citations", "in_submission", "valid")})
    out.update({f"check_{c}": row["checks"][c] for c in CHECKS})
    out.update({"cited_sessions": len(row["citations"]), "citations": " ".join(row["citations"]),
                "checks": "failed: " + ", ".join(failed) if failed else "all pass", "valid": row["valid"],
                "used": "yes" if row["in_submission"] else "no"})
    return out


def cell(text, limit: int = 70) -> str:
    text = str(text if text is not None else "").replace("\n", " ").replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "reactor_report.md")
    args = ap.parse_args()

    gold = {g["question_id"]: ("ABSTAIN" if g["abstain"] else g["answer"]) for g in load_jsonl(DATA / "dev/gold.jsonl")}
    sessions = {split: sessions_of(split) for split in ("dev", "test")}
    test_qids = [q["question_id"] for q in load_jsonl(DATA / "test/questions.jsonl")]
    rows = []
    for run in sorted((HERE / "runs").iterdir(), key=lambda d: (d.name in SUBMISSION, SUBMISSION.index(d.name)
                                                                 if d.name in SUBMISSION else 0, d.name)):
        path = run / "results.jsonl"
        if path.exists() and path.stat().st_size:
            rows += rows_of(run, set(test_qids), sessions, gold)
    # The call a test question's submission uses: the last answered one in the submission runs (re-asks come later).
    used = {}
    for row in rows:
        if row["run"] in SUBMISSION and row["status"] == "answered":
            used[row["question_id"]] = (row["run"], row["n"])
    for row in rows:
        row["in_submission"] = used.get(row["question_id"]) == (row["run"], row["n"])
        row["valid"] = all(row["checks"].values())

    lines = [f"# Reactor calls: results and checks",
             "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M} by `python report.py` from `runs/*/results.jsonl`: every "
             "line is one call to our Reactor agent (team OpenToVibe, slot t07) through the kit's `client.py`, "
             "exactly as the client returned it. Rows for every call are also in `reactor_calls.json`.",
             "",
             f"**Test coverage:** {len(used)} of {len(test_qids)} test questions have a Reactor answer "
             f"({len(test_qids) - len(used)} still to ask).",
             "",
             "## Summary per run",
             "",
             "| run | questions | calls | answered | all checks pass | abstained | median latency | max latency | "
             "busy retries | late replies set aside |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for run in dict.fromkeys(r["run"] for r in rows):
        rr = [r for r in rows if r["run"] == run]
        lat = [r["latency_s"] for r in rr if r["latency_s"]]
        purpose = "submission" if run in SUBMISSION else f"{rr[0]['split']} (testing)"
        lines.append(f"| {run} | {purpose} | {len(rr)} | {sum(r['status'] == 'answered' for r in rr)} | "
                     f"{sum(r['valid'] for r in rr)} | {sum(r['abstained'] for r in rr)} | "
                     f"{statistics.median(lat):.0f} s | {max(lat):.0f} s | {sum(r['retries'] for r in rr)} | "
                     f"{sum(r['late_replies'] for r in rr)} |")
    total_valid = sum(r["valid"] for r in rows)
    lines += ["", f"**All runs:** {len(rows)} calls, {sum(r['status'] == 'answered' for r in rows)} answered, "
              f"{total_valid} pass every check.", ""]

    lines += ["## Checks", "",
              "| check | meaning | calls failing |", "|---|---|---|"]
    meaning = {
        "answered": "client status `answered` (no timeout, refusal, closed chat or error)",
        "ref": "the reply's `# FINAL ANSWER [ref:…]` line carries this question's ref, so it answers this message",
        "citations": "every cited `[E#]` label is one we sent, and maps to a real session of that history",
        "cited": "an answer that is not an abstention cites at least one excerpt",
        "size": f"the message we sent was within the {MAX_CHARS:,}-character limit",
        "abstention": "abstained exactly when the answer is `INSUFFICIENT_EVIDENCE`",
    }
    for c in CHECKS:
        failing = [f"{r['run']}#{r['n']}" for r in rows if not r["checks"][c]]
        lines.append(f"| {c} | {meaning[c]} | {len(failing)}{': ' + ', '.join(failing) if failing else ''} |")
    late = [r for r in rows if r["late_replies"]]
    if late:
        lines += ["", "A *late reply* is a final answer to the previous question that arrived while the next one was "
                  "being asked. The client reports it separately and never takes it as the current answer: "
                  + ", ".join(f"{r['run']}#{r['n']} ({r['question_id']})" for r in late) + "."]

    drafted = [r for r in rows if r["run"] in SUBMISSION and r["draft"] is not None and r["status"] == "answered"]
    if drafted:
        differ = [r for r in drafted if not r["agrees_with_draft"]]
        lines += ["", "## Reactor and the second reader", "",
                  f"{len(drafted)} submission calls carried a DeepSeek draft. Reactor's final answer matches the draft "
                  f"(ignoring labels, case and punctuation) in {len(drafted) - len(differ)} and differs in "
                  f"{len(differ)}; Reactor checks the draft against the evidence and does not copy it.", "",
                  "| run | question | draft | Reactor |", "|---|---|---|---|"]
        lines += [f"| {r['run']}#{r['n']} | {cell(r['question'], 60)} | {cell(r['draft'], 45)} | "
                  f"{cell(r['answer'], 45)} |" for r in differ]

    for split in ("test", "dev"):
        rr = [r for r in rows if r["split"] == split]
        if not rr:
            continue
        lines += ["", f"## Every {split} call", ""]
        if split == "test":
            lines += ["`smoke` is our first connection test on three test questions; its answers are not used.", ""]
            lines += ["`in submission`: this call's answer is the one `predict.py` uses (a later re-ask replaces an "
                      "earlier answer).", "",
                      "| run | # | question | Reactor's answer | cited sessions | latency | checks | in submission |",
                      "|---|---|---|---|---|---|---|---|"]
        else:
            lines += ["| run | # | question | Reactor's answer | gold | latency | checks |",
                      "|---|---|---|---|---|---|---|"]
        for r in rr:
            checks = "✓" if r["valid"] else "✗ " + ", ".join(c for c in CHECKS if not r["checks"][c])
            lat = f"{r['latency_s']:.0f} s" if r["latency_s"] else "-"
            if split == "test":
                lines.append(f"| {r['run']} | {r['n']} | {cell(r['question'], 60)} | {cell(r['answer'] or r['error'], 50)} | "
                             f"{len(r['citations'])} | {lat} | {checks} | {'✓' if r['in_submission'] else ''} |")
            else:
                lines.append(f"| {r['run']} | {r['n']} | {cell(r['question'], 60)} | {cell(r['answer'] or r['error'], 45)} | "
                             f"{cell(r['gold'], 35)} | {lat} | {checks} |")

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.out.parent / "reactor_calls.json").write_text(json.dumps([flat(r) for r in rows], ensure_ascii=False, indent=1),
                                                        encoding="utf-8")
    print(f"{len(rows)} calls, {total_valid} pass every check; {len(used)}/{len(test_qids)} test questions answered "
          f"-> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
