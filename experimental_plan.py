"""Generate a reproducible OFFLINE Reactor experiment plan; never execute it.

Only runtime.prepare is called. Generated runtime commands are dry runs too.
Gold is used only for category/abstention stratification and evaluation files.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
from itertools import permutations
import json
from pathlib import Path
import shlex
import sys

from evaluate import partition
import runtime

ROOT = Path(__file__).resolve().parent
DIAGNOSTIC_ID = "q_d4ead82e5cad"
SEED = "reactor-memory-v1"
ARMS = (
    ("bm25-4", "bm25", "none"),
    ("calibrated-4", "calibrated", "none"),
    ("calibrated-memory", "calibrated", "targeted"),
)


def rank_id(value, seed=SEED):
    return hashlib.sha256((seed + "/" + value).encode()).hexdigest()


def choose_cohort(questions, gold, excluded_ids=(), paired_questions=12, seed=SEED):
    """Select natural shared histories, then five development-only singletons.

    Exclude entire histories containing diagnostic IDs or validation questions.
    Keep original within-history question order; never synthesize user histories.
    Gold answer/evidence fields are never consulted.
    """
    if paired_questions < 2:
        raise ValueError("paired_questions must be at least two")
    groups = defaultdict(list)
    for q in questions:
        groups[q["history_id"]].append(q)
    excluded = set(excluded_ids)
    eligible = {hid: rows for hid, rows in groups.items()
                if not any(q["question_id"] in excluded or partition(q["question_id"]) != "development"
                           for q in rows)}
    shared, used = [], set()
    for hid in sorted(eligible, key=lambda value: rank_id(value, seed)):
        rows = eligible[hid]
        if len(rows) >= 2 and len(shared) + len(rows) <= paired_questions:
            shared.extend(rows)
            used.add(hid)
    if not shared:
        raise ValueError("no eligible natural shared histories; do not fabricate stateful evaluation")
    strata = ["single-session-user", "multi-session", "knowledge-update", "temporal-reasoning", "unanswerable"]
    representative = []
    singletons = [rows[0] for hid, rows in eligible.items() if len(rows) == 1 and hid not in used]
    for stratum in strata:
        pool = []
        for q in singletons:
            g = gold.get(q["question_id"])
            if not g:
                raise ValueError("gold category labels missing for a development question")
            matches = bool(g["abstain"]) if stratum == "unanswerable" else (
                not g["abstain"] and g["question_type"] == stratum)
            if matches and q["history_id"] not in used:
                pool.append(q)
        if not pool:
            raise ValueError(f"no eligible singleton for stratum {stratum}")
        q = min(pool, key=lambda row: rank_id(stratum + "/" + row["question_id"], seed))
        representative.append(q)
        used.add(q["history_id"])
    return shared, representative


def write_jsonl(path, values):
    path.write_text("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values), encoding="utf-8")


def counts(questions, manifest):
    resets = len({q["history_id"] for q in questions})
    preloads = sum(len(parts) for parts in manifest.get("memory_parts", {}).values())
    return {"history_resets": resets, "question_requests": len(questions), "preload_requests": preloads,
            "initial_api_operations": resets + len(questions) + preloads}


def sum_counts(rows):
    keys = ("history_resets", "question_requests", "preload_requests", "initial_api_operations")
    return {key: sum(row[key] for row in rows) for key in keys}


def build_plan(args):
    out = args.out_dir.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("plan output directory contains artifacts; choose a new directory to preserve the frozen plan")
    source_questions = args.data / "questions.jsonl"
    source_histories = args.data / "histories.jsonl"
    source_gold = args.data / "gold.jsonl"
    questions = runtime.read_jsonl(source_questions)
    if len({q["question_id"] for q in questions}) != len(questions):
        raise ValueError("duplicate public question IDs")
    by_qid = {q["question_id"]: q for q in questions}
    gold = {g["question_id"]: g for g in runtime.read_jsonl(source_gold)}
    if DIAGNOSTIC_ID not in by_qid:
        raise ValueError("Stage 1 diagnostic question is missing")
    smoke = runtime.read_jsonl(args.smoke)
    if len(smoke) != 5 or any(by_qid.get(q["question_id"]) != q for q in smoke):
        raise ValueError("smoke must contain exactly five unchanged public development questions")
    excluded = {DIAGNOSTIC_ID, *(q["question_id"] for q in smoke)}
    shared, representative = choose_cohort(questions, gold, excluded, args.paired_questions, args.seed)
    cohort = shared + representative
    all_questions = [by_qid[DIAGNOSTIC_ID], *smoke, *cohort]
    wanted_histories = {q["history_id"] for q in all_questions}
    inputs = out / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    selected_histories = inputs / "histories.jsonl"
    # Preserve the original history lines byte-for-byte, including all sessions.
    # The subset avoids rereading the full 238 MB dev corpus for every arm.
    found = set()
    with source_histories.open("rb") as src, selected_histories.open("wb") as dst:
        for line in src:
            if not line.strip():
                continue
            hid = json.loads(line)["history_id"]
            if hid in wanted_histories:
                if hid in found:
                    raise ValueError("duplicate public history ID")
                dst.write(line if line.endswith(b"\n") else line + b"\n")
                found.add(hid)
    if found != wanted_histories:
        raise ValueError("selected histories missing from public data")
    source_hashes = {str(path.resolve()): runtime.file_sha256(path) for path in (
        Path(__file__), ROOT / "evaluate.py", ROOT / "smoke_report.py", ROOT / "compare_reactor.py", source_questions,
        source_histories, source_gold, args.smoke)}
    stages = []
    all_jobs = []

    def job(stage, name, rows, arm):
        arm_name, method, memory_mode = arm
        tag = f"{stage}/{name}/{arm_name}"
        directory = inputs / stage / name
        directory.mkdir(parents=True, exist_ok=True)
        qpath = directory / "questions.jsonl"
        gpath = directory / "gold.jsonl"
        write_jsonl(qpath, rows)
        write_jsonl(gpath, [gold[q["question_id"]] for q in rows])
        namespace = argparse.Namespace(questions=qpath, histories=selected_histories, question_ids=None,
            limit=0, method=method, k=4, budget=12000, max_chars=16000, client=ROOT / "reactor_client.py",
            base_url=args.base_url, agent_id=args.agent_id, memory_mode=memory_mode, memory_budget=args.memory_budget)
        prepared_questions, _, _, manifest = runtime.prepare(namespace)
        manifest_path = directory / (arm_name + "-runtime-manifest.json")
        runtime.atomic_json(manifest_path, manifest)
        run_dir = out / "runs" / tag
        command = [sys.executable, str(ROOT / "runtime.py"), "--questions", str(qpath), "--histories",
            str(selected_histories), "--out-dir", str(run_dir), "--limit", "0", "--method", method,
            "--k", "4", "--memory-mode", memory_mode, "--memory-budget", str(args.memory_budget),
            "--base-url", args.base_url, "--agent-id", args.agent_id]
        report_command = [sys.executable, str(ROOT / "smoke_report.py"), "--run", str(run_dir),
            "--questions", str(qpath), "--gold", str(gpath), "--out", str(out / "reports" / tag)]
        value = {"stage": stage, "name": name, "arm": arm_name, "method": method, "memory_mode": memory_mode,
            "question_ids": [q["question_id"] for q in prepared_questions],
            "history_ids": list(dict.fromkeys(q["history_id"] for q in prepared_questions)),
            "counts": counts(prepared_questions, manifest), "runtime_manifest": str(manifest_path),
            "runtime_manifest_sha256": runtime.file_sha256(manifest_path), "command_argv": command,
            "dry_run_command": shlex.join(command), "report_command": shlex.join(report_command),
            "report_json": str(out / "reports" / tag / "report.json"),
            "fresh_arm_output_directory": str(run_dir), "execute": False}
        all_jobs.append(value)
        return value

    first = job("stage1", "citation-gate", [by_qid[DIAGNOSTIC_ID]], ARMS[0])
    stages.append({"stage": "stage1", "diagnostic_bias": True, "jobs": [first], "counts": first["counts"]})
    second = job("stage2", "diverse-smoke", smoke, ARMS[0])
    stages.append({"stage": "stage2", "diagnostic_bias": True, "jobs": [second], "counts": second["counts"]})
    groups = defaultdict(list)
    for q in cohort:
        groups[q["history_id"]].append(q)
    orders = list(permutations(range(len(ARMS))))
    paired_jobs = []
    schedule = []
    # Six shared histories receive all six permutations before the singleton
    # diagnostic extends the schedule; this balances the primary memory cohort.
    history_order = sorted(groups, key=lambda value: (len(groups[value]) < 2, rank_id(value, args.seed)))
    for index, hid in enumerate(history_order):
        rows = groups[hid]
        name = f"history-{index + 1:02d}-{hid}"
        order = orders[index % len(orders)]
        schedule.append({"history_id": hid, "question_ids": [q["question_id"] for q in rows],
                         "cohort": "shared-memory" if len(rows) >= 2 else "representative-singleton",
                         "arm_order": [ARMS[i][0] for i in order]})
        for arm_index in order:
            paired_jobs.append(job("stage3", name, rows, ARMS[arm_index]))
    stages.append({"stage": "stage3", "selection_note": "new diagnostic IDs but development-trained and previously evaluated; not independent generalization", "jobs": paired_jobs,
                   "counts": sum_counts([j["counts"] for j in paired_jobs]), "schedule": schedule})
    compare_command = [sys.executable, str(ROOT / "compare_reactor.py")]
    for arm_name, _, _ in ARMS:
        for value in paired_jobs:
            if value["arm"] == arm_name:
                compare_command += ["--arm", arm_name + "=" + value["report_json"]]
    compare_command += ["--out", str(out / "paired-report.json")]
    histogram = Counter("unanswerable" if gold[q["question_id"]]["abstain"] else
                        gold[q["question_id"]]["question_type"] for q in cohort)
    plan = {"schema_version": 1, "mode": "offline-plan-only", "execute": False, "seed": args.seed,
        "source_sha256": source_hashes, "selected_histories_sha256": runtime.file_sha256(selected_histories),
        "stage3_selection": {"shared_questions": len(shared), "representative_singletons": len(representative),
            "total_questions": len(cohort), "histories": len(groups), "category_histogram": dict(sorted(histogram.items())),
            "partition": "development only; a shared history is excluded if either question is validation",
            "excluded_diagnostic_question_ids": sorted(excluded), "gold_use": "stratification and evaluation only"},
        "stages": stages, "total_initial_counts": sum_counts([stage["counts"] for stage in stages]),
        "compare_command_argv": compare_command, "compare_command": shlex.join(compare_command),
        "count_note": "Fresh histories per arm; excludes safe refusal retries, failed calls, recovery, and any larger evaluation.",
        "safety": ["No API calls are made by this planner or its generated commands.",
            "Run only the next stage after its acceptance gate passes; commands are not an execution driver.",
            "Only a designated runner with an actual mutually agreed exclusive window may add --execute, --exclusive-access, and --access-window.",
            "Every stage3 job starts in a separate output directory and must create its own history; never reuse another arm's checkpoint."]}
    runtime.atomic_json(out / "plan.json", plan)
    lines = ["# Offline commands", "", "These commands prepare evidence only. Stage gates and actual team access agreement remain required.", ""]
    for value in all_jobs:
        lines += [f"## {value['stage']} / {value['name']} / {value['arm']}", "", "```sh", value["dry_run_command"], "```", ""]
    lines += ["## Compare settled Stage-3 archives", "", "Run each job's report_command first. This command aggregates disjoint archives by arm without changing predictions.",
              "", "```sh", plan["compare_command"], "```", ""]
    (out / "commands.md").write_text("\n".join(lines), encoding="utf-8")
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/dev")
    parser.add_argument("--smoke", type=Path, default=ROOT / "smoke/questions.jsonl")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--paired-questions", type=int, default=12)
    parser.add_argument("--memory-budget", type=int, default=12000)
    parser.add_argument("--seed", default=SEED)
    parser.add_argument("--base-url", default="https://t07.api.reactor-hackathon.rxai.dev")
    parser.add_argument("--agent-id", default="agt_0c172edd3340495a")
    args = parser.parse_args(argv)
    if args.memory_budget <= 0:
        parser.error("memory-budget must be positive")
    try:
        plan = build_plan(args)
    except (OSError, ValueError, KeyError) as exc:
        print("experiment planning error: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"plan": str(args.out_dir / "plan.json"), "stage3_selection": plan["stage3_selection"],
                      "total_initial_counts": plan["total_initial_counts"], "execute": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
