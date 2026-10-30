"""Explicit development-label-only calibration. Deployment never imports this.

Predeclared variants: BM25 top32 and top64 turns. Fixed internal split uses
history hashes so related questions stay together. L2 and expected-F1 mass
multiplier use the internal 25% holdout. Final fit uses all 433 development
questions; validation labels are never loaded into training features/selection.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from evaluate import jsonl, partition, retrieval_metrics
from retrieval_calibrated import FEATURES, candidates, probabilities, select


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit(items, l2):
    x = np.array([r["features"] for item in items for r in item["rows"]])
    y = np.array([y for item in items for y in item["labels"]])
    mean, scale = x.mean(0), x.std(0)
    scale[scale < 1e-8] = 1
    x = np.column_stack([np.ones(len(x)), (x-mean)/scale])
    w = np.zeros(x.shape[1])
    # Newton steps for penalized logistic likelihood; intercept unpenalized.
    penalty = np.eye(x.shape[1])*l2
    penalty[0, 0] = 0
    for _ in range(40):
        p = 1/(1+np.exp(-np.clip(x@w, -35, 35)))
        grad = x.T@(p-y) + penalty@w
        hessian = x.T@((p*(1-p))[:, None]*x) + penalty + np.eye(len(w))*1e-8
        step = np.linalg.solve(hessian, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-7:
            break
    return {"features": FEATURES, "mean": mean.tolist(), "scale": scale.tolist(),
            "weights": w[1:].tolist(), "intercept": float(w[0]), "l2": l2}


def evaluate(items, artifact, mass):
    metrics, records = [], []
    for item in items:
        probs = probabilities(item["rows"], artifact)
        chosen = select(item["rows"], probs, mass, 4)
        prediction = [row["si"] for row in chosen]
        result = retrieval_metrics(prediction, item["evidence"])
        if result["evidence_f1"] is not None:
            metrics.append(result)
        records.append({"question_id": item["qid"], "predicted": prediction,
                        "gold": item["evidence"], "probabilities": probs,
                        "candidate_labels": item["labels"], **result})
    return {key: float(np.mean([m[key] for m in metrics]))
            for key in ("evidence_f1", "precision", "recall")}, records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/dev"))
    parser.add_argument("--out", type=Path, default=Path("experiments/calibration-r2"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    questions = {q["question_id"]: q for q in jsonl(args.data/"questions.jsonl")
                 if partition(q["question_id"]) == "development"}
    # Read labels only for development questions. Validation never enters this map.
    labels = {g["question_id"]: g for g in jsonl(args.data/"gold.jsonl")
              if g["question_id"] in questions}
    grouped = {}
    for q in questions.values():
        grouped.setdefault(q["history_id"], []).append(q)
    datasets = {32: [], 64: []}
    for history in jsonl(args.data/"histories.jsonl"):
        for q in grouped.get(history["history_id"], []):
            gold = labels[q["question_id"]]
            evidence = [i for i, s in enumerate(history["sessions"]) if s["session_id"] in gold["evidence"]]
            internal = int(hashlib.sha256(("calibration-r2:"+q["history_id"]).encode()).hexdigest()[:8], 16)%4
            for pool in datasets:
                rows = candidates(q, history, pool)
                datasets[pool].append({"qid": q["question_id"], "internal": internal,
                    "rows": rows, "labels": [int(r["si"] in evidence) for r in rows],
                    "evidence": evidence})
    trials = []
    for pool, items in datasets.items():
        train = [i for i in items if i["internal"] != 0]
        heldout = [i for i in items if i["internal"] == 0]
        for l2 in (.1, 1., 10.):
            artifact = fit(train, l2)
            for mass in (.5, 1., 2., 4.):
                metrics, _ = evaluate(heldout, artifact, mass)
                trials.append({"pool": pool, "l2": l2, "mass_multiplier": mass,
                               "train_n": len(train), "internal_holdout_n": len(heldout), **metrics})
    best = max(trials, key=lambda t: (t["evidence_f1"], -t["pool"], -t["l2"]))
    artifact = fit(datasets[best["pool"]], best["l2"])
    artifact.update({"pool": best["pool"], "mass_multiplier": best["mass_multiplier"],
                     "version": 1, "training_n": len(questions),
                     "selection": "history-grouped internal 75/25 split; maximize mean answerable session F1; max four sessions",
                     "source_sha256": {str(p): sha(p) for p in [Path(__file__), Path("retrieval_calibrated.py"), args.data/"questions.jsonl", args.data/"histories.jsonl", args.data/"gold.jsonl"]}})
    Path("models").mkdir(exist_ok=True)
    model_path = Path("models/session_selection.json")
    model_path.write_text(json.dumps(artifact, indent=2)+"\n")
    development, records = evaluate(datasets[best["pool"]], artifact, best["mass_multiplier"])
    summary = {"best_internal": best, "trials": trials, "development_fit_diagnostic": development,
               "development_n": len(questions), "development_answerable_n": sum(not g["abstain"] for g in labels.values()),
               "model_sha256": sha(model_path), "elapsed_s": time.perf_counter()-started,
               "note": "In-sample development diagnostic is optimistic; only internal heldout used for parameter selection. Validation not consumed."}
    (args.out/"training.json").write_text(json.dumps(summary, indent=2)+"\n")
    with (args.out/"development-fit-details.jsonl").open("w") as f:
        for record in records:
            f.write(json.dumps(record)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
