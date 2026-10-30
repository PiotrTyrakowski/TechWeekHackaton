"""Evaluate an automatic attribution policy on REAL saved Reactor answers offline.

Gold is consumed only by the official scorer. The attribution callable receives
only question, original history/evidence, and saved Reactor result. Historical
predictions are never edited; a new policy prediction is an explicit derivative.
No gold-answer oracle generation and no live/hosted AI calls are implemented.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

from evaluation_diagnostics import lines, load_snapshot, sha, unique, write_new
from official import score
from official.reactor import predictions as adapter
from official.reactor.client import citations as parse_citations

FIELDS = {"policy_version", "reactor_citations", "fallback_citations", "unresolved_claims", "supports", "final_citations"}


def citation_ids(citations):
    if not isinstance(citations, list):
        raise ValueError("Attribution citation field must be a list")
    ids = [c if isinstance(c, str) else c.get("id", c.get("session_id")) if isinstance(c, dict) else None for c in citations]
    if not all(isinstance(cid, str) and cid for cid in ids):
        raise ValueError("Attribution must provide valid session IDs")
    return list(dict.fromkeys(ids))


def verify_support_records(supports, history, evidence, fallback_ids):
    """Independently check provenance integrity; semantic rules belong to policy."""
    if not isinstance(supports, list):
        raise ValueError("Support records must be a list")
    sessions = {s["session_id"]: s for s in history["sessions"]}
    verified_ids = set()
    for support in supports:
        if not isinstance(support, dict):
            raise ValueError("Invalid support record")
        index, start, end = (support.get(k) for k in ("evidence_index", "start", "end"))
        if any(type(v) is not int for v in (index, start, end)) or not 0 <= index < len(evidence):
            raise ValueError("Invalid support evidence index or offsets")
        passage = evidence[index]
        sid, role, span = (support.get(k) for k in ("source_id", "role", "span"))
        if sid != passage["id"] or sid not in sessions or role not in {"user", "assistant"}:
            raise ValueError("Invalid support source/role")
        if not isinstance(span, str) or not span or not 0 <= start < end <= len(passage["text"]) or passage["text"][start:end] != span:
            raise ValueError("Support span does not match original evidence offsets")
        if not any(t.get("role") == role and span in t.get("content", "") for t in sessions[sid].get("turns", [])):
            raise ValueError("Support span absent from original same-role history turn")
        if not support.get("claim") or not support.get("rule"):
            raise ValueError("Support lacks claim/verification rule")
        verified_ids.add(sid)
    if set(fallback_ids) - verified_ids:
        raise ValueError("Fallback lacks independently checked source support")


def evaluate_policy(questions, gold, histories, evidence_by_qid, results, original_predictions, attribute_answer):
    qmap, gmap, hmap = unique(questions), unique(gold), unique(histories, "history_id")
    rmap, original = unique(results), unique(original_predictions)
    if set(rmap) != set(original):
        raise ValueError("Use the complete original saved results/predictions; do not select successful subsets")
    if set(rmap) - set(qmap) or set(qmap) - set(gmap):
        raise ValueError("Unknown output question or missing evaluation gold")
    errors = score.validate(original_predictions, set(qmap))
    if errors:
        raise ValueError("; ".join(errors))
    historical_scores, policy_scores, policy_predictions, rows = [], [], [], []
    for qid, raw in rmap.items():
        if raw.get("status") != "answered":
            raise ValueError("Only real completed Reactor answers may enter attribution evaluation")
        q = qmap[qid]
        h, evidence = hmap[q["history_id"]], evidence_by_qid[qid]
        valid = {s["session_id"]: s["date"] for s in h["sessions"]}
        if any(e.get("id") not in valid or e.get("date") != valid[e["id"]] for e in evidence):
            raise ValueError("Evidence must preserve original same-history source and date")
        actual_citations, actual_unknown = parse_citations(raw.get("answer", ""), evidence)
        if actual_citations != raw.get("citations", []) or actual_unknown != raw.get("unknown_citations", []):
            raise ValueError("Saved citation metadata differs from actual marked final answer")
        converted, skipped, notes = adapter.convert([raw], {"agent"}, set(valid))
        if skipped or notes or converted != [original[qid]]:
            raise ValueError("Historical prediction does not match official conversion of saved raw answer")
        # Deliberately no gold parameter and no closure over gmap in this call.
        attribution = attribute_answer(copy.deepcopy(q), copy.deepcopy(h), copy.deepcopy(evidence), copy.deepcopy(raw))
        if not isinstance(attribution, dict) or not FIELDS <= set(attribution):
            raise ValueError("Incomplete attribution provenance contract")
        if not isinstance(attribution["policy_version"], str) or not attribution["policy_version"] or not isinstance(attribution["unresolved_claims"], list):
            raise ValueError("Invalid attribution policy version/unresolved-claims schema")
        supplied = citation_ids(attribution["reactor_citations"])
        fallback = citation_ids(attribution["fallback_citations"])
        final = citation_ids(attribution["final_citations"])
        if set(supplied + fallback + final) - set(valid):
            raise ValueError("Attribution cited a foreign-history session")
        if set(supplied + fallback + final) - {e["id"] for e in evidence}:
            raise ValueError("Attribution must cite original supplied evidence, not unseen sessions")
        if set(final) - set(supplied + fallback):
            raise ValueError("Final citations have no supplied/fallback attribution")
        if set(supplied) != set(original[qid]["citations"]):
            raise ValueError("Policy changed Reactor-supplied citation provenance")
        verify_support_records(attribution["supports"], h, evidence, fallback)
        policy = {**original[qid], "citations": final}
        if policy["abstain"] and final:
            raise ValueError("An abstention cannot acquire answer evidence")
        old_score = score.score_question(original[qid], gmap[qid])
        new_score = score.score_question(policy, gmap[qid])
        historical_scores.append(old_score)
        policy_scores.append(new_score)
        policy_predictions.append(policy)
        rows.append({"question_id": qid, "question_record": q,
            "saved_reactor_result_sha256": sha(json.dumps(raw, sort_keys=True).encode()),
            "original_evidence_sha256": sha(json.dumps(evidence, sort_keys=True).encode()),
            "historical_prediction_unchanged": original[qid], "new_automatic_policy_prediction": policy,
            "attribution": attribution, "reactor_supplied_session_ids": supplied,
            "fallback_provenance_independently_checked": True,
            "verified_fallback_session_ids": fallback, "unresolved_claims": attribution["unresolved_claims"],
            "historical_official_local_result": old_score, "policy_official_local_result": new_score,
            "actual_citation_f1_delta": None if gmap[qid]["abstain"] else new_score["evidence_f1"] - old_score["evidence_f1"]})
    policy_map = unique(policy_predictions)
    return {"kind": "actual-saved-reactor-output-attribution-evaluation", "oracle_proxy": False,
        "new_reactor_calls": 0, "external_hosted_ai_calls": 0, "official_llm_judge_run": False,
        "scope": {"public_dev_questions": len(qmap), "available_real_reactor_answers": len(rmap),
                  "public_dev_answerable": sum(not gmap[k]["abstain"] for k in qmap),
                  "available_real_answerable_outputs": sum(not gmap[k]["abstain"] for k in rmap),
                  "available_output_coverage": len(rmap) / len(qmap) if qmap else None,
                  "missing_output_n": len(qmap) - len(rmap)},
        "historical_actual_outputs_official_local": score.summarize(historical_scores) if historical_scores else {},
        "new_policy_actual_outputs_official_local": score.summarize(policy_scores) if policy_scores else {},
        "full_scope_new_policy_official_submission": score.summarize([score.score_question(policy_map.get(k), gmap[k]) for k in qmap]) if qmap else {},
        "attribution_counts": {"outputs_with_reactor_supplied_citations": sum(bool(r["reactor_supplied_session_ids"]) for r in rows),
            "outputs_with_verified_fallback_citations": sum(bool(r["verified_fallback_session_ids"]) for r in rows),
            "outputs_with_unresolved_claims": sum(bool(r["unresolved_claims"]) for r in rows)},
        "per_question": rows,
        "interpretation": "Official evidence F1 applies to actual saved answers and the explicit new automatic policy derivative. This is not newly generated Reactor performance. Small/selective output coverage cannot establish benchmark accuracy or fallback generalization. Local answer matching is not official Reactor accuracy; missing outputs are submission penalties, not observed wrong model answers. No gold-answer oracle proxy is included."}, policy_predictions


def load_policy(path):
    path = path.resolve()
    name = "exact_attribution_" + sha(str(path).encode())[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load attribution module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.attribute_answer


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "questions", "gold", "histories", "attribution-file", "out"):
        ap.add_argument("--" + name, type=Path, required=True)
    args = ap.parse_args(argv)
    if args.out.exists():
        raise ValueError("Preserve existing report; choose a fresh output directory")
    files = load_snapshot(args.run)
    parse = lambda name: [json.loads(x) for x in files.get(name, b"").decode().splitlines() if x.strip()]
    questions, gold = lines(args.questions), lines(args.gold)
    results, predictions = parse("results.jsonl"), parse("predictions.jsonl")
    qmap = unique(questions)
    selected_histories = {qmap[r["question_id"]]["history_id"] for r in results}
    histories, history_raw = [], []
    with args.histories.open("rb") as stream:
        for line in stream:
            if line.strip():
                h = json.loads(line)
                if h["history_id"] in selected_histories:
                    histories.append(h)
                    history_raw.append(line)
    evidence = {}
    for r in results:
        qid = r["question_id"]
        key = "evidence/" + sha(qid.encode()) + ".json"
        if key not in files:
            raise ValueError("Original evidence is required; pass the original run directory, not its older evidence-free archive")
        evidence[qid] = json.loads(files[key])
    policy_raw = args.attribution_file.read_bytes()
    policy = load_policy(args.attribution_file)
    report, derived = evaluate_policy(questions, gold, histories, evidence, results, predictions, policy)
    files["evaluation-questions.jsonl"] = args.questions.read_bytes()
    files["evaluation-gold.jsonl"] = args.gold.read_bytes()
    files["original-selected-histories.jsonl"] = b"".join(history_raw)
    if args.attribution_file.read_bytes() != policy_raw:
        raise ValueError("Attribution source changed during evaluation; rerun after owner freezes it")
    files["attribution-policy.py"] = policy_raw
    key = os.environ.get("REACTOR_ACCESS_KEY", "").encode()
    if any((key and key in raw) or re.search(rb"rxk_[A-Za-z0-9_-]{8,}", raw) for raw in files.values()):
        raise ValueError("Refusing credential-containing archive")
    report["input_sha256"] = {name: sha(raw) for name, raw in files.items()}
    report["evaluator_sha256"] = sha(Path(__file__).read_bytes())
    report["scorer_sha256"] = sha(Path(score.__file__).read_bytes())
    report["adapter_sha256"] = sha(Path(adapter.__file__).read_bytes())
    report["attribution_file"] = str(args.attribution_file.resolve())
    args.out.mkdir(parents=True)
    for name, raw in files.items():
        path = args.out / "historical-raw" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (args.out / "new-policy-predictions.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in derived))
    write_new(args.out / "report.json", report)
    print(json.dumps({k: report[k] for k in ("scope", "attribution_counts", "historical_actual_outputs_official_local", "new_policy_actual_outputs_official_local")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
