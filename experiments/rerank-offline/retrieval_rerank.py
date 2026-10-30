"""Cheap deterministic BM25 reranking with query coverage and phrase boosts.

This module is an evaluator-compatible alternative and has no gold-data inputs.
"""
from __future__ import annotations

import re
from collections import Counter

import retrieval


def _tokens(text: str) -> list[str]:
    return retrieval.tokenize(text)


def _score(question: str, content: str, bm25: float) -> float:
    q = _tokens(question)
    d = _tokens(content)
    if not q or not d:
        return bm25
    qset, dset = set(q), set(d)
    # Favor documents covering distinct query concepts; tiny BM25-scale boosts
    # keep this a reranker instead of replacing the lexical candidate ranking.
    coverage = len(qset & dset) / len(qset)
    compact = " ".join(d)
    phrase = " ".join(q)
    phrase_boost = 0.16 if len(q) > 1 and phrase in compact else 0.0
    # Small penalty for very verbose turns with no additional query coverage.
    verbosity = min(max(len(d) - 100, 0), 500) / 500 * 0.08
    return bm25 + 0.42 * coverage + phrase_boost - verbosity


def retrieve(question: dict, history: dict, k: int = 4, method: str = "rerank",
             budget: int = 12000) -> list[dict]:
    """Return up to k session passages, ranked and packed within budget chars."""
    if method not in ("rerank", "rerank-diverse"):
        raise ValueError("method must be 'rerank' or 'rerank-diverse'")
    if k < 1 or budget < 1:
        raise ValueError("k and budget must be positive")
    base = retrieval._rank(question, history)
    sessions = history["sessions"]
    candidates = []
    for bm25, si, ti in base:
        turn = sessions[si]["turns"][ti]
        score = _score(question["question"], turn["content"], bm25)
        candidates.append((score, bm25, si, ti, f"{turn['role']}: {turn['content']}"))
    candidates.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
    # A retrieved session is one evidence item. Keep its strongest matching turn.
    unique = []
    seen = set()
    for item in candidates:
        if item[2] not in seen:
            seen.add(item[2])
            unique.append(item)
    if method == "rerank-diverse":
        # Alternate scoring with a mild date/session-order tie preference only;
        # dedup already ensures one slot per session.
        unique.sort(key=lambda x: (-x[0], x[2], x[3]))
    out, used = [], 0
    for _, _, si, _, text in unique:
        if len(out) >= k:
            break
        remaining = budget - used
        if remaining <= 0:
            break
        packed = text[:remaining]
        if not packed:
            continue
        session = sessions[si]
        out.append({"id": session["session_id"], "date": session["date"], "text": packed})
        used += len(packed)
    return out
