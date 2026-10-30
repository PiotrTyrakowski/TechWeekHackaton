"""Freeze a minimal Gates 0–4 plan using local inputs only; never execute it.

The legacy 95-operation design remains untouched. Every emitted runtime command
is a dry run. A team agreement and a single appointed runner are prerequisites
for any later live operation; this planner cannot grant either.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shlex
import sys

from evaluate import partition
import runtime

ROOT = Path(__file__).resolve().parent
DIAGNOSTIC_ID = "q_d4ead82e5cad"
SEED = "reactor-small-gates-v1"


def rank(value, seed):
    return hashlib.sha256((seed + "/" + value).encode()).hexdigest()


def select_pairs(questions, smoke, seed=SEED):
    """Choose two natural two-question development histories using public IDs.

    Exclude every history containing a smoke or validation question. The smoke
    pair must sort after the cat history because runtime groups users by ID and
    --stop-after 1 must reach the cat first. Preserve supplied within-user order.
    No gold, retrieval results, or answer correctness enters this selection.
    """
    groups = defaultdict(list)
    for question in questions:
        groups[question["history_id"]].append(question)
    excluded = {q["history_id"] for q in smoke}
    cat = next(q for q in smoke if q["question_id"] == DIAGNOSTIC_ID)
    eligible = {hid: rows for hid, rows in groups.items() if hid not in excluded
                and len(rows) == 2
                and all(partition(q["question_id"]) == "development" for q in rows)}
    smoke_candidates = sorted((hid for hid in eligible if hid > cat["history_id"]),
                              key=lambda hid: rank("smoke/" + hid, seed))
    if not smoke_candidates:
        raise ValueError("no natural development pair can follow the cat in runtime order")
    smoke_hid = smoke_candidates[0]
    paired = sorted((hid for hid in eligible if hid != smoke_hid),
                    key=lambda hid: rank("comparison/" + hid, seed))
    if not paired:
        raise ValueError("need a second natural development pair for the comparison")
    return eligible[smoke_hid], eligible[paired[0]]


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def counts(resets=0, questions=0, preloads=0):
    return {"history_resets": resets, "question_requests": questions,
            "preload_requests": preloads, "initial_api_operations": resets + questions + preloads}


def build_plan(args):
    out = args.out_dir.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("choose a new output directory; frozen artifacts are never overwritten")
    qsource, hsource, gsource = (args.data / name for name in
                                ("questions.jsonl", "histories.jsonl", "gold.jsonl"))
    questions = runtime.read_jsonl(qsource)
    by_id = {q["question_id"]: q for q in questions}
    if len(by_id) != len(questions):
        raise ValueError("duplicate public question IDs")
    smoke = runtime.read_jsonl(args.smoke)
    if (len(smoke) != 5 or len({q["question_id"] for q in smoke}) != 5
            or any(by_id.get(q["question_id"]) != q for q in smoke)
            or DIAGNOSTIC_ID not in {q["question_id"] for q in smoke}):
        raise ValueError("smoke must contain five unchanged public questions including the cat")
    if len({q["history_id"] for q in smoke}) != 5:
        raise ValueError("expected five original singleton smoke histories")
    gold = {g["question_id"]: g for g in runtime.read_jsonl(gsource)}
    if not any(gold[q["question_id"]]["abstain"] for q in smoke):
        raise ValueError("smoke must contain an abstention probe")
    smoke_types = {gold[q["question_id"]]["question_type"] for q in smoke
                   if not gold[q["question_id"]]["abstain"]}
    if not {"single-session-user", "single-session-assistant", "multi-session", "knowledge-update"} <= smoke_types:
        raise ValueError("smoke must retain user, assistant, multi-session and update coverage")
    smoke_pair, comparison_pair = select_pairs(questions, smoke, args.seed)
    wanted = {q["history_id"] for q in smoke + smoke_pair + comparison_pair}
    inputs = out / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    histories = inputs / "histories.jsonl"
    found = set()
    with hsource.open("rb") as source, histories.open("wb") as dest:
        for line in source:
            if not line.strip():
                continue
            hid = json.loads(line)["history_id"]
            if hid in wanted:
                if hid in found:
                    raise ValueError("duplicate selected history")
                found.add(hid)
                dest.write(line if line.endswith(b"\n") else line + b"\n")
    if found != wanted:
        raise ValueError("selected public history is missing")
    jobs = {}

    def job(name, rows, method, memory="none"):
        directory = inputs / name
        directory.mkdir()
        qpath, gpath = directory / "questions.jsonl", directory / "gold.jsonl"
        write_jsonl(qpath, rows)
        write_jsonl(gpath, [gold[q["question_id"]] for q in rows])
        ns = argparse.Namespace(questions=qpath, histories=histories, question_ids=None,
            limit=0, method=method, k=4, budget=12000, max_chars=16000,
            timeout=300, client=ROOT / "reactor_client.py", base_url=args.base_url,
            agent_id=args.agent_id, memory_mode=memory, memory_budget=args.memory_budget)
        prepared, _, evidence, manifest = runtime.prepare(ns)
        manifest_path = directory / "runtime-manifest.json"
        runtime.atomic_json(manifest_path, manifest)
        runtime.atomic_json(directory / "evidence.json", evidence)
        for hid, parts in ns.prepared_memory.items():
            for index, part in enumerate(parts):
                (directory / f"memory-{hid}-{index + 1}.txt").write_text(part, encoding="utf-8")
        argv = [sys.executable, str(ROOT / "runtime.py"), "--questions", str(qpath),
            "--histories", str(histories), "--out-dir", str(out / "runs" / name),
            "--limit", "0", "--method", method, "--k", "4", "--budget", "12000",
            "--memory-mode", memory, "--memory-budget", str(args.memory_budget),
            "--base-url", args.base_url, "--agent-id", args.agent_id]
        report = [sys.executable, str(ROOT / "smoke_report.py"), "--run", str(out / "runs" / name),
                  "--questions", str(qpath), "--gold", str(gpath), "--out", str(out / "reports" / name)]
        value = {"job_id": name, "method": method, "memory_mode": memory,
            "question_ids": manifest["question_ids"], "history_ids": list(dict.fromkeys(q["history_id"] for q in prepared)),
            "counts": counts(len({q["history_id"] for q in prepared}), len(prepared),
                             sum(map(len, manifest["memory_parts"].values()))),
            "runtime_manifest": str(manifest_path), "runtime_manifest_sha256": runtime.file_sha256(manifest_path),
            "evidence_sha256": manifest["evidence_sha256"],
            "per_question_evidence_sha256": {qid: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
                                              for qid, value in evidence.items()},
            "prepared_e1_session_by_question": {qid: entries[0]["id"] if entries else None
                                                 for qid, entries in evidence.items()},
            "comparability_identity": {"question_ids_in_runtime_order": manifest["question_ids"],
                "questions_sha256": manifest["questions_sha256"], "histories_sha256": manifest["histories_sha256"],
                "source_sha256": {name: digest for name, digest in manifest["source_sha256"].items()
                                  if name != "reactor_memory.py"},
                "client_sha256": manifest["client_sha256"], "k": 4, "budget": 12000,
                "max_chars": 16000, "timeout_s": 300, "base_url": args.base_url,
                "agent_id": args.agent_id},
            "command_argv": argv, "dry_run_command": shlex.join(argv),
            "report_command_argv": report, "report_command": shlex.join(report),
            "report_json": str(out / "reports" / name / "report.json"),
            "execute": False}
        jobs[name] = value
        return value

    smoke_job = job("smoke-bm25", smoke + smoke_pair, "bm25")
    if smoke_job["question_ids"][0] != DIAGNOSTIC_ID:
        raise ValueError("cat must be first after actual runtime history grouping")
    bm25 = job("paired-bm25", comparison_pair, "bm25")
    calibrated = job("paired-calibrated", comparison_pair, "calibrated")
    memory = job("paired-calibrated-memory", comparison_pair, "calibrated", "targeted")
    if calibrated["evidence_sha256"] != memory["evidence_sha256"]:
        raise ValueError("memory arm changed final-question evidence")
    if calibrated["comparability_identity"] != memory["comparability_identity"]:
        raise ValueError("memory arm changed baseline provenance")
    cat_command = smoke_job["command_argv"] + ["--stop-after", "1"]
    interim_report = smoke_job["report_command_argv"][:-1] + [str(out / "reports" / "gate1-interim")]
    order = ["paired-bm25", "paired-calibrated"]
    if int(rank("arm-order/" + comparison_pair[0]["history_id"], args.seed), 16) % 2:
        order.reverse()
    gates = [
        {"gate": 0, "status": "requires-local-validation", "counts": counts(),
         "command_argv": [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
         "acceptance": ["All local protocol, citation, isolation, failure-recovery, and planner tests pass.",
                        "Mocks/simulations are labelled offline; no model quality is inferred."]},
        {"gate": 1, "status": "blocked-exclusive-access", "counts": counts(1, 1),
         "job_ids": ["smoke-bm25"], "command_argv": cat_command,
         "dry_run_command": shlex.join(cat_command),
         "interim_report_command_argv": interim_report,
         "interim_report_command": shlex.join(interim_report),
         "report_note": "Interim archive uses its own directory. Six intentionally unattempted Gate-2 questions remain explicit; assess Gate 1 on the cat row only.",
         "acceptance": ["Actual current-ref marked answer is correct with a correct nonempty final-segment citation.",
                        "Official adapter accepts actual prediction; local answer correct and Evidence F1 equals 1.",
                        "No uncertain pending operation, foreign history, or unexplained protocol failure."]},
        {"gate": 2, "status": "blocked-gate-1", "counts": counts(5, 6),
         "job_ids": ["smoke-bm25"], "resume_same_manifest": True,
         "command_argv": smoke_job["command_argv"], "dry_run_command": smoke_job["dry_run_command"],
         "acceptance": ["Continue exact Gate-1 run/checkpoint; do not repeat its completed cat question.",
                        "Complete all seven predeclared questions, including real abstention and both natural same-user questions.",
                        "The known unanswerable probe must produce an actual marked INSUFFICIENT_EVIDENCE abstention; a transport failure cannot satisfy this check.",
                        "Exactly one reset for each dataset history; no reset between the natural pair.",
                        "Validate current-question citation mapping and report every wrong/unjudged/uncited answer and failure.",
                        "Stop expansion on protocol/isolation failure; ordinary wrong answers remain in results."]},
        {"gate": 3, "status": "blocked-gate-2", "counts": counts(2, 4),
         "job_ids": order, "fresh_history_per_arm": True,
         "acceptance": ["Run both frozen retrieval arms sequentially in the specified order with fresh arm histories.",
                        "Report paired actual answer outcomes, citation F1, abstention, failures, latency and operations.",
                        "One two-question history is an integration pilot and cannot establish a general winner."]},
        {"gate": 4, "status": "blocked-gate-3", "counts": memory["counts"],
         "job_ids": ["paired-calibrated-memory"], "baseline_job_id": "paired-calibrated",
         "baseline_reuse": {"conditional": True,
             "requires": ["Completed, unchanged Gate-3 calibrated archive and no unresolved pending call.",
                          "Identical original questions/order, exact evidence hash, source hashes, prompt/client, dates and budgets.",
                          "Baseline is evidence-only; preload arm starts fresh and loads exact prepared bounded parts."],
             "fallback_additional_counts": counts(1, 2)},
         "identical_final_evidence_sha256": calibrated["evidence_sha256"],
         "acceptance": ["Compare unchanged evidence-only baseline against the bounded preload arm on identical questions.",
                        "Baseline reuse is predeclared here; incomplete/uncertain archives stop the gate. No automatic replay or fallback.",
                        "Report first versus second question outcomes; retain all preload replies separately from predictions.",
                        "Disclose query-aware future-question pooling and order/time confounding; gain cannot isolate native memory.",
                        "One pair does not support a benchmark or statistical improvement claim."]}]
    total = {key: sum(g["counts"][key] for g in gates) for key in counts()}
    compare = {}
    for name, arm_jobs in (("gate3", [bm25, calibrated]), ("gate4", [calibrated, memory])):
        if arm_jobs[0]["comparability_identity"] != arm_jobs[1]["comparability_identity"]:
            raise ValueError("contrast changed code/data/order/prompt provenance")
        argv = [sys.executable, str(ROOT / "compare_reactor.py")]
        for arm in arm_jobs:
            argv.extend(["--arm", arm["job_id"] + "=" + arm["report_json"]])
        argv.extend(["--out", str(out / (name + "-comparison.json"))])
        compare[name] = {"command_argv": argv, "command": shlex.join(argv),
            "comparability_identity": arm_jobs[0]["comparability_identity"],
            "require_identical_final_evidence": name == "gate4",
            "per_arm_question_evidence_sha256": {arm["job_id"]: arm["per_question_evidence_sha256"] for arm in arm_jobs},
            "warning": "Existing comparer is descriptive and checks question/gold equality only. Independently verify these frozen identities against settled run artifacts before interpreting a contrast."}
    plan = {"schema_version": 1, "mode": "offline-plan-only", "execute": False,
        "live_runner": None, "exclusive_access_confirmed": False, "seed": args.seed,
        "gates": gates, "jobs": jobs, "comparisons": compare,
        "total_initial_counts_conditional_baseline_reuse": total,
        "source_sha256": {str(path.resolve()): runtime.file_sha256(path)
            for path in (Path(__file__), ROOT / "evaluate.py", ROOT / "smoke_report.py",
                         ROOT / "compare_reactor.py", qsource, hsource, gsource, args.smoke)},
        "selected_histories_sha256": runtime.file_sha256(histories),
        "selection": {"smoke_shared_question_ids": [q["question_id"] for q in smoke_pair],
            "comparison_question_ids": [q["question_id"] for q in comparison_pair],
            "pair_categories": {name: [gold[q["question_id"]]["question_type"] for q in rows]
                                for name, rows in (("smoke", smoke_pair), ("comparison", comparison_pair))},
            "pair_gold_source_sets_equal": {name: len({tuple(sorted(gold[q["question_id"]]["evidence"])) for q in rows}) == 1
                                            for name, rows in (("smoke", smoke_pair), ("comparison", comparison_pair))},
            "policy": "Public IDs only; whole-history development exclusion; original within-history order; no retrieval/answer filtering.",
            "limits": "Reused development diagnostics, development-trained calibrated model, one comparison history; not independent generalization. Temporal coverage is deferred. Current natural assistant pairs repeat gold source sets and prepared E1 sources: they test sequencing, not cross-source label remapping robustness or retrieval discrimination. True cross-source remapping is covered by local synthetic protocol tests only. Do not select replacement pairs based on retrieval disagreement."},
        "cost": {"monetary_usd": None, "reason": "No price or usage tariff established by inspected kit.",
            "operations_exclude": "Safe refused retries, failed calls, uncertain in-flight calls and explicitly coordinated recovery.",
            "latency": "Measure Gate 1/2 before forecasting; one historical 46.63s answer is not representative."},
        "safety": ["This file is a plan, not an execution driver; no automatic gate transitions.",
            "All generated runtime commands are dry runs; no access attestation is created.",
            "Before any live call, explicitly confirm cross-machine exclusive access and appoint exactly one runner.",
            "Do not execute the legacy 95-operation plan automatically.",
            "Preserve actual outputs; never repair final answers/citations or selectively retry wrong completed answers."]}
    runtime.atomic_json(out / "plan.json", plan)
    lines = ["# Minimal offline gate plan", "", "No live access is authorized. Commands below are dry runs. Execute only one accepted gate at a time after actual team coordination.", ""]
    for gate in gates:
        lines.extend([f"## Gate {gate['gate']}", "", f"Initial incremental operations: {gate['counts']['initial_api_operations']}.", ""])
        if "dry_run_command" in gate:
            lines.extend(["```sh", gate["dry_run_command"], "```", ""])
        elif gate["gate"] > 2:
            for jid in gate["job_ids"]:
                lines.extend(["```sh", jobs[jid]["dry_run_command"], "```", ""])
        lines.extend(["Acceptance: " + " ".join(gate["acceptance"]), ""])
    lines.extend(["Gate 4 reuses Gate 3's calibrated baseline only after exact provenance verification; otherwise add three baseline operations in a new run directory.", "",
                  "Gate 1 has a separate interim_report_command; reserve the smoke job's final report directory for Gate 2. Report archives are never overwritten.", "",
                  "Run each job's report command after settlement, then the separate compare commands in plan.json. No answer judge or Reactor call is made by those reporters.", ""])
    (out / "commands.md").write_text("\n".join(lines), encoding="utf-8")
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=ROOT / "data/dev")
    ap.add_argument("--smoke", type=Path, default=ROOT / "smoke/questions.jsonl")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--seed", default=SEED)
    ap.add_argument("--memory-budget", type=int, default=12000)
    ap.add_argument("--base-url", default="https://t07.api.reactor-hackathon.rxai.dev")
    ap.add_argument("--agent-id", default="agt_0c172edd3340495a")
    args = ap.parse_args(argv)
    if args.memory_budget <= 0:
        ap.error("memory-budget must be positive")
    try:
        plan = build_plan(args)
    except (OSError, ValueError, KeyError) as exc:
        print("gate planning error: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"plan": str(args.out_dir / "plan.json"), "execute": False,
        "incremental_initial_operations": {g["gate"]: g["counts"]["initial_api_operations"] for g in plan["gates"]},
        "total_initial_counts_conditional_baseline_reuse": plan["total_initial_counts_conditional_baseline_reuse"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
