"""Freeze small experiment gates OFFLINE; no execution path or Reactor client.

Writes exact question records, source evidence, and prefix-only preload payloads.
The current runtime's all-question targeted memory must NOT substitute for these
prefix payloads. Execution requires a separately reviewed runner and approval.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from evaluation_diagnostics import lines, partition, sha, unique, write_new
from reactor_memory import prepare_memory
from retrieval import retrieve

SEED = "independent-validity-gates-v1"
DIAGNOSTICS = ("q_d4ead82e5cad", "q_1773242b1801")
STRATA = ("single-session-user", "single-session-assistant", "multi-session",
          "knowledge-update", "temporal-reasoning", "unanswerable")


def rank(value):
    return sha((SEED + "/" + value).encode())


def select(questions, gold):
    groups = defaultdict(list)
    for q in questions:
        groups[q["history_id"]].append(q)
    diagnostic_histories = {q["history_id"] for q in questions if q["question_id"] in DIAGNOSTICS}
    eligible = {hid: rows for hid, rows in groups.items() if hid not in diagnostic_histories
                and all(partition(q["question_id"]) == "development" for q in rows)}
    used = set(diagnostic_histories)
    def singleton(stratum):
        # Assistant questions occur in natural pairs in this release. Isolate
        # the first original question for category coverage, reserving different
        # complete pairs for the sequential gate.
        pool = [rows[0] for hid, rows in eligible.items() if (len(rows) == 1 or stratum == "single-session-assistant") and hid not in used
                and (gold[rows[0]["question_id"]]["abstain"] if stratum == "unanswerable" else
                     not gold[rows[0]["question_id"]]["abstain"] and gold[rows[0]["question_id"]]["question_type"] == stratum)]
        if not pool:
            raise ValueError("No eligible singleton: " + stratum)
        q = min(pool, key=lambda q: rank(q["question_id"]))
        used.add(q["history_id"])
        return q
    gate2 = [singleton(s) for s in STRATA]
    pairs = [rows for hid, rows in sorted(eligible.items(), key=lambda item: rank(item[0])) if len(rows) == 2 and hid not in used][:2]
    if len(pairs) != 2:
        raise ValueError("Need two natural two-question histories")
    used.update(rows[0]["history_id"] for rows in pairs)
    gate4 = [singleton(s) for s in (*STRATA, "single-session-user", "multi-session")]
    qmap = unique(questions)
    return [[qmap[k] for k in DIAGNOSTICS], gate2, [q for rows in pairs for q in rows], gate4]


def build(data, out):
    if out.exists():
        raise ValueError("Choose a fresh output directory")
    questions = lines(data / "questions.jsonl")
    gold = unique(lines(data / "gold.jsonl"))
    cohorts = select(questions, gold)
    wanted = {q["history_id"] for cohort in cohorts for q in cohort}
    histories = {}
    with (data / "histories.jsonl").open() as stream:
        for line in stream:
            if line.strip():
                h = json.loads(line)
                if h["history_id"] in wanted:
                    histories[h["history_id"]] = h
    if set(histories) != wanted:
        raise ValueError("Missing source histories")
    out.mkdir(parents=True)
    gates = []
    for index, cohort in enumerate(cohorts, 1):
        directory = out / f"gate{index}"
        directory.mkdir()
        for name, rows in (("questions", cohort), ("gold", [gold[q["question_id"]] for q in cohort])):
            (directory / (name + ".jsonl")).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        evidence_hashes = {}
        for q in cohort:
            for method in ("bm25", "calibrated"):
                evidence = retrieve(q, histories[q["history_id"]], method=method, k=4, budget=12000)
                dates = {s["session_id"]: s["date"] for s in histories[q["history_id"]]["sessions"]}
                if any(e.get("date") != dates.get(e["id"]) for e in evidence):
                    raise ValueError("Evidence source/date changed")
                path = directory / (q["question_id"] + "-" + method + ".json")
                write_new(path, evidence)
                evidence_hashes[path.name] = {"sha256": sha(path.read_bytes()), "text_chars": sum(len(e["text"]) for e in evidence)}
        groups = defaultdict(list)
        for q in cohort:
            groups[q["history_id"]].append(q)
        preloads = {}
        if index in (3, 4):
            for hid, rows in groups.items():
                # Never consult the later public question to construct memory.
                parts = prepare_memory(histories[hid], [rows[0]], budget=6000)
                path = directory / (hid + "-prefix-memory.json")
                write_new(path, parts)
                preloads[hid] = {"source_question_ids": [rows[0]["question_id"]], "parts": len(parts),
                                 "chars": sum(map(len, parts)), "sha256": sha(path.read_bytes())}
        n, h, p = len(cohort), len(groups), sum(v["parts"] for v in preloads.values())
        resets = h if index == 1 else 2 * h
        turns = n if index == 1 else 2 * n
        preload_count = p if index == 3 else 0
        gates.append({"gate": index, "questions": cohort, "category_histogram": dict(Counter(
            "unanswerable" if gold[q["question_id"]]["abstain"] else gold[q["question_id"]]["question_type"] for q in cohort)),
            "arm_order_by_history": {hid: (["calibrated-4"] if index == 1 else
                (["calibrated-4", "calibrated-prefix-memory"] if index == 3 else
                 ["calibrated-4", "bm25-4"] if index == 2 else ["calibrated-4", "frozen-candidate"])[::1 if i % 2 == 0 else -1]) for i, hid in enumerate(groups)},
            "initial_operations": {"resets": resets, "question_requests": turns, "preloads": preload_count,
                                   "total": resets + turns + preload_count},
            "conditional_extra_preloads_if_gate4_memory_winner": p if index == 4 else 0,
            "prefix_preloads": preloads, "evidence": evidence_hashes})
    plan = {"mode": "offline-proposal-only-not-the-execution-plan", "execute": False, "seed": SEED, "gates": gates,
            "timeout_s": 600, "primary_baseline": "calibrated-4", "execution_plan_owner": "lead; use lead-owned 23-operation gate_plan only",
            "initial_operations_total_without_optional_controls": sum(g["initial_operations"]["total"] for g in gates),
            "source_sha256": {str(data / name): sha((data / name).read_bytes()) for name in ("questions.jsonl", "gold.jsonl", "histories.jsonl")},
            "code_sha256": {name: sha((Path(__file__).parent / name).read_bytes()) for name in ("evaluation_gates.py", "evaluation_diagnostics.py", "retrieval.py", "retrieval_calibrated.py", "reactor_memory.py", "models/session_selection.json")},
            "constraint": "OFFLINE until explicit cross-machine exclusivity and one authorized runner. Each gate needs explicit live approval and prior raw-results review. Use 600s timeout, normal pending backoff 5-10s; timeout may keep processing: preserve same history, never reset on timeout. Prefix-memory execution is not implemented by this proposal; do not substitute pooled targeted memory. No future question or gold enters preload. Gates 2-4 are development diagnostics, not clean holdouts. Preserve final 146-question window (2.5h or longer), never auto-launch. No external hosted AI API in pipeline; Reactor final answer required."}
    write_new(out / "plan.json", plan)
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    plan = build(args.data, args.out)
    print(json.dumps({"initial_operations": [g["initial_operations"] for g in plan["gates"]], "execute": False}))


if __name__ == "__main__":
    main()
