"""Frozen supervised session selection from BM25 candidates; offline, no labels.

The model consumes only query and candidate text/statistics. Question, history,
and session identifiers are used only to return the original evidence identity.
``k`` bounds the maximum selected sessions (default four); model probabilities
choose the subset size by the development-calibrated expected-F1 surrogate.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from retrieval import _rank, _excerpt, tokenize

FEATURES = [
    "best_score", "relative_best", "relative_second", "score_share", "log_rank",
    "next_gap", "leader_gap", "hit_count", "user_best", "assistant_best",
    "user_fraction", "best_coverage", "union_coverage", "query_length",
    "turn_length", "session_length", "pool_sessions", "multi_query",
    "time_query", "count_query", "assistant_query", "update_query",
    "multi_relative", "time_relative", "count_relative", "assistant_role_match",
    "exact_phrase", "number_overlap", "top_score", "top_gap",
]


def candidates(question, history, pool=64):
    """At most pool BM25 turns, grouped into sessions without label filtering."""
    ranked = _rank(question, history)[:pool]
    if not ranked:
        return []
    query = set(tokenize(question["question"]))
    text = question["question"].lower()
    multi = float(bool(re.search(r"\b(all|both|each|different|across|compare|list|activities|hobbies|places|things|changes)\b", text)))
    temporal = float(bool(re.search(r"\b(before|after|first|last|latest|recent|earlier|when|since|during)\b", text)))
    count = float(bool(re.search(r"\b(how many|number of|total|times)\b", text)))
    assistant = float(bool(re.search(r"\b(you|suggest|recommend|advice|assistant)\b", text)))
    update = float(bool(re.search(r"\b(now|currently|changed|update|new|still|anymore)\b", text)))
    groups = {}
    for rank, (score, si, ti) in enumerate(ranked):
        groups.setdefault(si, []).append((rank, score, ti))
    maximum = ranked[0][0]
    total = sum(row[0] for row in ranked)
    session_scores = sorted((rows[0][1] for rows in groups.values()), reverse=True)
    result = []
    for si, hits in groups.items():
        session = history["sessions"][si]
        rank, best, ti = hits[0]
        turn = session["turns"][ti]
        tokens = set(tokenize(turn["content"]))
        union = set().union(*(set(tokenize(session["turns"][h[2]]["content"])) for h in hits))
        user_scores = [score for _, score, t in hits if session["turns"][t]["role"] == "user"]
        assistant_scores = [score for _, score, t in hits if session["turns"][t]["role"] == "assistant"]
        position = session_scores.index(best)
        next_score = session_scores[position + 1] if position + 1 < len(session_scores) else 0
        relative = best / maximum
        words = [w for w in tokenize(question["question"]) if len(w) > 2]
        phrase = max((len(" ".join(words[start:start+2])) for start in range(len(words)-1)
                      if " ".join(words[start:start+2]) in turn["content"].lower()), default=0)
        numbers = set(re.findall(r"\d+", text))
        features = [
            math.log1p(best), relative, hits[1][1] / maximum if len(hits) > 1 else 0,
            sum(s for _, s, _ in hits) / total, math.log1p(rank),
            (best-next_score)/maximum, (maximum-best)/maximum, math.log1p(len(hits)),
            max(user_scores, default=0)/maximum, max(assistant_scores, default=0)/maximum,
            len(user_scores)/len(hits), len(query & tokens)/max(len(query), 1),
            len(query & union)/max(len(query), 1), math.log1p(len(query)),
            math.log1p(len(turn["content"])), math.log1p(len(session["turns"])),
            math.log1p(len(groups)), multi, temporal, count, assistant, update,
            multi*relative, temporal*relative, count*relative,
            assistant*float(turn["role"] == "assistant"), math.log1p(phrase),
            len(numbers & set(re.findall(r"\d+", turn["content"]))) / max(len(numbers), 1),
            math.log1p(maximum), (maximum-session_scores[1])/maximum if len(session_scores)>1 else 1,
        ]
        result.append({"si": si, "hits": [t for _, _, t in hits], "features": features})
    return result


@lru_cache(maxsize=1)
def model():
    artifact = json.loads((Path(__file__).parent / "models/session_selection.json").read_text())
    if artifact["features"] != FEATURES:
        raise ValueError("Model feature schema mismatch")
    return artifact


def probabilities(rows, artifact):
    result = []
    for row in rows:
        linear = artifact["intercept"] + sum(
            weight * (value-mean) / scale for value, mean, scale, weight in
            zip(row["features"], artifact["mean"], artifact["scale"], artifact["weights"]))
        result.append(1 / (1 + math.exp(-max(-35, min(35, linear)))))
    return result


def select(rows, probs, calibration=1.0, limit=4):
    """Maximize 2*expected true positives/(selected + calibrated total mass).

    This plug-in expectation is a surrogate, not the exact expectation of F1.
    The mass multiplier is fitted on internal development only. Always return
    at least one candidate when available; absence confidence is diagnostic.
    """
    order = sorted(range(len(rows)), key=lambda i: (-probs[i], i))
    total = sum(probs) * calibration
    best_value, best_n, running = -1, 0, 0
    for n, i in enumerate(order[:limit], 1):
        running += probs[i]
        value = 2 * running / (n + total)
        if value > best_value:
            best_value, best_n = value, n
    return [rows[i] for i in order[:best_n]]


def retrieve(question, history, k=4, method="calibrated", budget=12000):
    if method != "calibrated":
        from retrieval import retrieve as base
        return base(question, history, k=k, method=method, budget=budget)
    if k < 1 or budget < 1:
        raise ValueError("k and budget must be positive")
    artifact = model()
    rows = candidates(question, history, artifact["pool"])
    chosen = select(rows, probabilities(rows, artifact), artifact["mass_multiplier"], k)
    if not chosen:
        return []
    cap = budget // len(chosen)
    result = []
    for row in chosen:
        session = history["sessions"][row["si"]]
        # Two best turns plus adjacent turns, best hits retained first under cap.
        hits = row["hits"][:2]
        packed, remaining = {}, cap
        neighbors = sorted({j for i in hits for j in (i-1, i, i+1)
                            if 0 <= j < len(session["turns"])})
        for ti in hits + [i for i in neighbors if i not in hits]:
            text = _excerpt(session["turns"][ti])
            if ti in hits or len(text)+1 <= remaining:
                packed[ti] = text[:max(0, remaining)]
                remaining -= len(packed[ti])+1
                if remaining <= 0:
                    break
        result.append({"id": session["session_id"], "date": session["date"],
                       "text": "\n".join(packed[i] for i in sorted(packed))[:cap]})
    return result
