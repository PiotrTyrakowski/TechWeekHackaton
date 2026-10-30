"""In-sample development-only cap diagnostic; never fits, ranks, or reads validation.

Run from the worktree: PYTHONPATH=. python experiments/calibration-r2-robust/cap_diagnostic_evaluator.py
"""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import statistics

from evaluate import partition, retrieval_metrics
from retrieval_calibrated import FEATURES, probabilities, select

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent / "development-features.jsonl.gz"
ARTIFACT = ROOT / "models/session_selection.json"
OUTPUT = ROOT / "experiments/calibration-r2/cap-diagnostic.json"


def main():
    model = json.loads(ARTIFACT.read_text())
    if model["features"] != FEATURES or model["pool"] != 64:
        raise ValueError("Original top64/30-feature artifact required; no recomputation allowed")
    groups = collections.defaultdict(list)
    with gzip.open(CACHE, "rt") as stream:
        for line in stream:
            item = json.loads(line)
            if item["pool"] != 64:
                continue
            if partition(item["qid"]) != "development":
                raise ValueError("Unexpected non-development observation")
            for row in item["rows"]:
                if len(row["features"]) != 31:
                    raise ValueError("Exact original thirty-feature prefix unavailable")
                row["features"] = row["features"][:30]
            groups[item["variant"]].append(item)
    report = {
        "scope": "IN-SAMPLE exploratory development diagnostic; original model fitted on dev433; dev-large uses the same question IDs and labels with augmented distractors",
        "warning": "No validation, new ranking, fitting, tuning, answer calls, or promotion. Metrics cannot establish held-out performance.",
        "feature_contract": "Cached top64 rows; original exact thirty-feature prefix; original artifact and mass multiplier unchanged",
        "artifact_sha256": hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(),
        "cache_sha256": hashlib.sha256(CACHE.read_bytes()).hexdigest(),
        "by_variant": {},
    }
    for variant, items in sorted(groups.items()):
        if len(items) != 433 or len({i["qid"] for i in items}) != 433:
            raise ValueError("Complete development433 top64 cache required")
        answerable = [i for i in items if i["evidence"]]
        distribution = collections.Counter(len(i["evidence"]) for i in answerable)
        data = {"questions_n": len(items), "answerable_n": len(answerable),
                "gold_session_count_distribution": dict(sorted(distribution.items())),
                "gold_exceeds_four_n": sum(len(i["evidence"]) > 4 for i in answerable),
                "gold_exceeds_four_all_gold_in_candidate_pool_n": sum(
                    len(i["evidence"]) > 4 and sum(i["labels"]) == len(i["evidence"])
                    for i in answerable),
                "all_gold_in_candidate_pool_n": sum(sum(i["labels"]) == len(i["evidence"]) for i in answerable),
                "caps": {}}
        outcomes = {}
        for cap in (4, 6, 8):
            results, all_results = [], []
            additions_true = additions_false = selected_over_four = 0
            changes = collections.Counter()
            recovered_structural = []
            for item in items:
                probs = probabilities(item["rows"], model)
                selected = select(item["rows"], probs, model["mass_multiplier"], cap)
                ids = [r["si"] for r in selected]
                metric = retrieval_metrics(ids, item["evidence"])
                all_results.append((len(ids), bool(item["evidence"])))
                selected_over_four += len(ids) > 4
                if not item["evidence"]:
                    continue
                results.append(metric)
                if cap == 4:
                    outcomes[item["qid"]] = {"selected": ids, **metric}
                baseline = outcomes[item["qid"]]
                delta = metric["evidence_f1"] - baseline["evidence_f1"]
                changes["better" if delta > 1e-9 else "worse" if delta < -1e-9 else "equal"] += 1
                added = set(ids) - set(baseline["selected"])
                additions_true += len(added & set(item["evidence"]))
                additions_false += len(added - set(item["evidence"]))
                if len(item["evidence"]) > 4 and metric["all_hit"]:
                    recovered_structural.append(item["qid"])
            data["caps"][str(cap)] = {
                **{name: statistics.mean(r[name] for r in results)
                   for name in ("precision", "recall", "evidence_f1", "all_hit", "any_hit")},
                "all_gold_recovered_n": sum(r["all_hit"] == 1 for r in results),
                "mean_selected_sessions_all_questions": statistics.mean(n for n, _ in all_results),
                "selected_more_than_four_all_questions_n": selected_over_four,
                "selected_more_than_four_answerable_n": sum(n > 4 and answerable for n, answerable in all_results),
                "f1_changes_vs_cap4": dict(changes),
                "added_sessions_vs_cap4": {"scope": "answerable questions only", "true": additions_true, "false": additions_false,
                    "precision": additions_true/(additions_true+additions_false) if additions_true+additions_false else None},
                "gold_exceeds_four_all_recovered_n": len(recovered_structural),
                "gold_exceeds_four_recovered_question_ids": recovered_structural,
            }
        report["by_variant"][variant] = data
    OUTPUT.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
