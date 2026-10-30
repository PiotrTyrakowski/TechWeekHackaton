"""Read-only research audit; no Reactor imports, transports, or runtime execution.

Usage: python3 offline_audit.py --source-root /path/to/checkout > audit.json
The source root needs the pinned official/ checkout and downloaded dev inputs.
Only pure parser functions are compiled from their AST, excluding all imports
and transport code. Gold is read for evaluation diagnostics only.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re


def records(path):
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def pure_functions(path, names, constants):
    tree = ast.parse(path.read_text())
    selected = [node for node in tree.body if (
        isinstance(node, ast.FunctionDef) and node.name in names
    ) or (
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets)
    )]
    namespace = {"re": re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def audit(root):
    client = root / "official/reactor/client.py"
    adapter = root / "official/reactor/predictions.py"
    question_path = root / "data/dev/questions.jsonl"
    gold_path = root / "data/dev/gold.jsonl"
    parser = pure_functions(client, {"final_answers", "citations"}, {"_FINAL"})
    stripper = pure_functions(adapter, {"strip_labels"}, {"_LABELS"})
    evidence = [{"id": "s_alpha", "text": "alpha"}, {"id": "s_beta", "text": "beta"}]
    probes = []
    for text in ["Luna [E1] [E2]", "Luna [E1, E2]", "Luna [E1/E2]", "Luna [source E1]",
                 "Luna [e1]", "Luna E1", "Luna [s_alpha]", "Luna [E01]", "Luna [E0]"]:
        cited, unknown = parser["citations"](text, evidence)
        probes.append({"text": text, "citations": cited, "unknown": unknown,
                       "stripped": stripper["strip_labels"](text)})
    finals = {}
    for name, text in {
        "before_marker": "Luna [E1]\n# FINAL ANSWER [ref:1234abcd]: Luna",
        "after_marker_on_next_line": "# FINAL ANSWER [ref:1234abcd]: Luna\n[E1]",
        "repeated_same_ref": "# FINAL ANSWER [ref:1234abcd]: old [E1]\n# FINAL ANSWER [ref:1234abcd]: new [E2]",
    }.items():
        answer = parser["final_answers"](text)["1234abcd"]
        finals[name] = {"answer": answer, "citations": parser["citations"](answer, evidence)[0]}
    groups = defaultdict(list)
    questions, gold = records(question_path), {g["question_id"]: g for g in records(gold_path)}
    for q in questions:
        groups[q["history_id"]].append(q)
    shared = [qs for qs in groups.values() if len(qs) > 1]
    pairs = [(a, b) for qs in shared for i, a in enumerate(qs) for b in qs[i + 1:]]
    output = {
        "network_calls": 0,
        "parser_probes": probes,
        "final_segment_probes": finals,
        "label_remapping": {
            "first_call": parser["citations"]("Luna [E1]", evidence)[0],
            "second_call_reordered": parser["citations"]("Luna [E1]", evidence[::-1])[0],
            "no_current_evidence": parser["citations"]("Luna [E1]", []),
            "same_session_two_passages": parser["citations"]("Luna [E1] [E2]", [evidence[0], evidence[0]])[0],
        },
        "development_cohort": {
            "questions": len(questions), "histories": len(groups),
            "group_size_counts": dict(Counter(map(len, groups.values()))),
            "shared_histories": len(shared), "shared_questions": sum(map(len, shared)),
            "shared_question_types": dict(Counter(gold[q["question_id"]]["question_type"] for qs in shared for q in qs)),
            "shared_abstentions": sum(gold[q["question_id"]]["abstain"] for qs in shared for q in qs),
            "pairs": len(pairs),
            "pairs_identical_gold_session_sets": sum(
                set(gold[a["question_id"]]["evidence"]) == set(gold[b["question_id"]]["evidence"])
                for a, b in pairs),
        },
    }
    detail = root / "experiments/maximum-score-r2/dev-large-calibrated-full/20261030T223408144377Z/0-calibrated-k4-details.jsonl"
    scored = [r for r in records(detail) if not r["gold_abstain"]]
    ceiling = []
    for r in scored:
        hits = len(set(r["retrieved_sessions"]) & set(r["gold_sessions"]))
        ceiling.append(2 * hits / (hits + len(set(r["gold_sessions"]))))
    output["cached_dev_large_calibrated"] = {
        "answerable": len(scored),
        "all_retrieved_cited_mean_f1": sum(r["evidence_f1"] for r in scored) / len(scored),
        "oracle_selective_citation_mean_f1_ceiling": sum(ceiling) / len(ceiling),
        "note": "Fixed source IDs only; ignores excerpt sufficiency. Full set includes fitted questions. Not Reactor performance.",
    }
    output["input_sha256"] = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (client, adapter, question_path, gold_path, detail)
    }
    return output


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--source-root", required=True, type=Path)
    print(json.dumps(audit(args.parse_args().source_root), indent=2, sort_keys=True))
