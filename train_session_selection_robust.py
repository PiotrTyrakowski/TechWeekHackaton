"""One bounded, paired-history dev/dev-large augmentation round; no validation fitting."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from evaluate import jsonl, partition
from retrieval import _rank
from retrieval_calibrated import ROBUST_FEATURES, candidates
from train_session_selection import evaluate


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fit(items, l2):
    x = np.array([r["features"] for item in items for r in item["rows"]])
    y = np.array([y for item in items for y in item["labels"]])
    mean, scale = x.mean(0), x.std(0)
    scale[scale < 1e-8] = 1
    x = np.column_stack([np.ones(len(x)), (x-mean)/scale])
    w = np.zeros(x.shape[1])
    penalty = np.eye(x.shape[1])*l2
    penalty[0, 0] = 0
    for _ in range(40):
        # einsum avoids spurious macOS Accelerate floating-point status flags.
        p = 1/(1+np.exp(-np.clip(np.einsum('ij,j->i', x, w), -35, 35)))
        grad = np.einsum('ij,i->j', x, p-y) + np.einsum('ij,j->i', penalty, w)
        hessian = np.einsum('ij,ik,i->jk', x, x, p*(1-p)) + penalty + np.eye(len(w))*1e-8
        step = np.linalg.solve(hessian, grad)
        w -= step
        if not np.isfinite(w).all():
            raise ValueError("Nonfinite fit")
        if np.max(np.abs(step)) < 1e-7:
            break
    return {"features": ROBUST_FEATURES, "mean": mean.tolist(), "scale": scale.tolist(),
            "weights": w[1:].tolist(), "intercept": float(w[0]), "l2": l2}


def main():
    started = time.perf_counter()
    out = Path("experiments/calibration-r2-robust")
    out.mkdir(parents=True, exist_ok=True)
    datasets = {32: [], 64: []}
    source_paths = [Path(__file__), Path("retrieval_calibrated.py"), Path("train_session_selection.py")]
    development_ids = None
    for variant in ("dev", "dev-large"):
        directory = Path("data")/variant
        questions = {q["question_id"]: q for q in jsonl(directory/"questions.jsonl")
                     if partition(q["question_id"]) == "development"}
        if development_ids is not None and set(questions) != development_ids:
            raise ValueError("Augmentation question scope mismatch")
        development_ids = set(questions)
        labels = {g["question_id"]: g for g in jsonl(directory/"gold.jsonl") if g["question_id"] in questions}
        grouped = {}
        for q in questions.values():
            grouped.setdefault(q["history_id"], []).append(q)
        count = 0
        for history in jsonl(directory/"histories.jsonl"):
            for q in grouped.get(history["history_id"], []):
                if time.perf_counter()-started > 300:
                    raise TimeoutError("Five-minute extraction/fit budget exceeded; no partial model produced")
                gold = labels[q["question_id"]]
                evidence = [i for i, s in enumerate(history["sessions"]) if s["session_id"] in gold["evidence"]]
                internal = int(hashlib.sha256(("calibration-r2:"+q["history_id"]).encode()).hexdigest()[:8], 16)%4
                ranked = _rank(q, history)[:64]
                for pool in datasets:
                    rows = candidates(q, history, pool, ranked=ranked, robust=True)
                    datasets[pool].append({"qid": q["question_id"], "variant": variant,
                        "history_id": q["history_id"], "internal": internal,
                        "rows": rows, "labels": [int(r["si"] in evidence) for r in rows], "evidence": evidence})
                count += 1
                if count % 50 == 0:
                    print(json.dumps({"variant": variant, "completed": count, "elapsed_s": time.perf_counter()-started}), flush=True)
        source_paths += [directory/name for name in ("questions.jsonl", "histories.jsonl", "gold.jsonl")]
    # Cache only development candidate statistics, never validation data.
    with (out/"development-features.jsonl").open("w") as stream:
        for pool, items in datasets.items():
            for item in items:
                stream.write(json.dumps({"pool": pool, **item})+"\n")
    trials = []
    for pool, items in datasets.items():
        train = [i for i in items if i["internal"] != 0]
        heldout = [i for i in items if i["internal"] == 0]
        for l2 in (.1, 1., 10.):
            artifact = fit(train, l2)
            for mass in (.5, 1., 2., 4.):
                metrics, _ = evaluate(heldout, artifact, mass)
                by_variant = {v: evaluate([i for i in heldout if i["variant"] == v], artifact, mass)[0]
                              for v in ("dev", "dev-large")}
                trials.append({"pool": pool, "l2": l2, "mass_multiplier": mass,
                    "train_augmented_n": len(train), "holdout_augmented_n": len(heldout),
                    "by_variant": by_variant, **metrics})
    best = max(trials, key=lambda t: (t["evidence_f1"], -t["pool"], -t["l2"]))
    artifact = fit(datasets[best["pool"]], best["l2"])
    artifact.update({"pool": best["pool"], "mass_multiplier": best["mass_multiplier"], "version": 2,
        "training_unique_questions_n": len(development_ids), "training_augmented_n": len(datasets[best["pool"]]),
        "selection": "same grouped internal split as R2; mean dev/dev-large answerable F1; top32/64 x L2 .1/1/10 x mass .5/1/2/4",
        "source_sha256": {str(p): sha(p) for p in source_paths}})
    model_path = Path("models/session_selection_robust.json")
    model_path.write_text(json.dumps(artifact, indent=2)+"\n")
    summary = {"best_internal": best, "trials": trials, "model_sha256": sha(model_path),
               "elapsed_s": time.perf_counter()-started, "note": "Both augmentation copies stay in same history fold. Validation never used for fitting or parameter selection. Frozen before exploratory validation reuse."}
    (out/"training.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
