"""Post-freeze paired analysis of evaluator artifacts; no fitting or raw gold reads."""
import json
import collections
import gzip
import hashlib
from pathlib import Path
import random
import statistics

HERE = Path(__file__).resolve().parent
ROOT = Path("/Users/zoga/Dev/Playground/TechWeekHackaton")


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def summarize(group):
    return {"n": len(group), "answerable_n": sum(r["evidence_f1"] is not None for r in group),
            **{key: statistics.mean(r[key] for r in group if r[key] is not None)
               for key in ("precision", "recall", "evidence_f1", "any_hit", "all_hit")}}


def compare(new, old):
    by_id = {r["question_id"]: r for r in old}
    differences = [r["evidence_f1"]-by_id[r["question_id"]]["evidence_f1"]
                   for r in new if r["evidence_f1"] is not None]
    rng = random.Random(42)
    bootstrap = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(10000))
    return {"f1_delta": statistics.mean(differences),
            "paired_bootstrap95_percentile": [bootstrap[250], bootstrap[9749]],
            "better": sum(d > 1e-9 for d in differences),
            "worse": sum(d < -1e-9 for d in differences),
            "equal": sum(abs(d) <= 1e-9 for d in differences)}


def main():
    original_all = rows(HERE.parent/"calibration-r2/final/20261030T222832152993Z/0-calibrated-k4-details.jsonl")
    train_histories = {r["history_id"] for r in original_all if r["partition"] == "development"}
    baselines = {
        "dev": {"old_calibrated": original_all,
                "dense_hybrid": rows(HERE.parent/"dense-full16/dense-hybrid-k4-details.jsonl")},
        "dev-large": {
            "old_calibrated": rows(ROOT/"experiments/maximum-score-r2/dev-large-calibrated-validation/20261030T223127751060Z/0-calibrated-k4-details.jsonl"),
            "dense_hybrid": rows(ROOT/"experiments/maximum-score-r2/dev-large-dense-validation/20261030T223005592968Z/0-dense-hybrid-k4-details.jsonl")}}
    report = {"note": "Reused exploratory validation; no further model selection. Paired question bootstrap seed42,10000 samples."}
    for variant in ("dev", "dev-large"):
        path = next((HERE/variant).glob("*/0-calibrated-robust-k4-details.jsonl"))
        new = rows(path)
        report[variant] = {}
        for name, group in [("all", new),
                            ("unseen_history", [r for r in new if r["history_id"] not in train_histories]),
                            ("shared_history", [r for r in new if r["history_id"] in train_histories])]:
            report[variant][name] = {**summarize(group), "comparison": {
                method: compare(group, old) for method, old in baselines[variant].items()}}
    groups = collections.defaultdict(list)
    with gzip.open(HERE/"development-features.jsonl.gz", "rt") as stream:
        for line in stream:
            item = json.loads(line)
            if item["evidence"]:
                groups[item["variant"], item["pool"]].append(item)
    report["development_candidate_coverage"] = {}
    for (variant, pool), group in groups.items():
        hits = [sum(item["labels"]) for item in group]
        report["development_candidate_coverage"][f"{variant}-pool{pool}"] = {
            "answerable_n": len(group),
            "mean_recall": statistics.mean(h/len(r["evidence"]) for h, r in zip(hits, group)),
            "all_gold_in_pool_n": sum(h == len(r["evidence"]) for h, r in zip(hits, group))}
    model_path = HERE.parents[1]/"models/session_selection_robust.json"
    report["history_feature_weight_standardized"] = json.loads(model_path.read_text())["weights"][-1]
    report["original_model_sha256"] = hashlib.sha256((HERE.parents[1]/"models/session_selection.json").read_bytes()).hexdigest()
    (HERE/"analysis.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
