"""Deterministic, dependency-free turn retrieval; never consumes gold answers.

``official`` reproduces the organizer's keyword baseline. ``bm25`` ranks
individual turns. ``bm25-context`` ranks distinct sessions by their best turn
and packs relevant turns plus their immediate neighbors, preserving chronology.
Budgets count passage text; the official client checks the final message limit.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from official.reactor.examples.run_benchmark import retrieve as official_retrieve

METHODS = ("official", "bm25", "bm25-context")
STOPWORDS = set("a an the i me my mine we us our you your it its this that these those "
                "is am are was were be been being do does did have has had can could "
                "would should will shall may might must to of in on at by for with "
                "from as and or but if then than so not no what which who whom whose "
                "when where why how about tell please recall remember said say".split())


def tokenize(text: str) -> list[str]:
    """Keep names and short numbers; lightly normalize plural nouns."""
    words = re.findall(r"[^\W_]+", text.lower())
    return [w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w
            for w in words if w not in STOPWORDS]


def _rank(question: dict, history: dict) -> list[tuple[float, int, int]]:
    query = set(tokenize(question["question"]))
    if not query:
        return []
    docs = []
    df = Counter()
    total_length = 0
    for si, session in enumerate(history["sessions"]):
        for ti, turn in enumerate(session["turns"]):
            terms = Counter(tokenize(turn["content"]))
            length = sum(terms.values())
            total_length += length
            df.update(terms.keys() & query)
            docs.append((si, ti, terms, length))
    n = len(docs)
    if not n:
        return []
    avgdl = max(total_length / n, 1)
    idf = {w: math.log(1 + (n - df[w] + .5) / (df[w] + .5)) for w in query}
    scored = []
    for si, ti, terms, length in docs:
        norm = 1.2 * (.25 + .75 * length / avgdl)
        score = sum(idf[w] * terms[w] * 2.2 / (terms[w] + norm)
                    for w in query & terms.keys())
        if score:
            scored.append((score, si, ti))
    return sorted(scored, key=lambda row: (-row[0], row[1], row[2]))


def _excerpt(turn: dict) -> str:
    return f"{turn['role']}: {turn['content']}"


def retrieve(question: dict, history: dict, k: int = 4, method: str = "bm25",
             budget: int = 12000) -> list[dict]:
    """Return client evidence dictionaries with history-local dates/session IDs.

    k means turns for official/bm25 and distinct sessions for bm25-context.
    Official uses the organizer's exact fixed 12,000-character implementation;
    it rejects a smaller budget to avoid silently changing the baseline.
    """
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; choose {METHODS}")
    if k < 1 or budget < 1:
        raise ValueError("k and budget must be positive")
    if method == "official":
        if budget != 12000:
            raise ValueError("official baseline requires budget=12000")
        return official_retrieve(question, history, k)
    ranked = _rank(question, history)
    sessions = history["sessions"]
    if method == "bm25":
        selected = [(si, _excerpt(sessions[si]["turns"][ti]))
                    for _, si, ti in ranked[:k]]
    else:
        # Each selected session gets its best two turns and adjacent context.
        # Rank sessions by maximum turn score: no advantage for long sessions.
        chosen = list(dict.fromkeys(si for _, si, _ in ranked))[:k]
        selected = []
        for si in chosen:
            turns = sessions[si]["turns"]
            hits = [ti for _, sj, ti in ranked if sj == si][:2]
            indices = sorted({neighbor for ti in hits for neighbor in (ti - 1, ti, ti + 1)
                              if 0 <= neighbor < len(turns)})
            # Retain best hits first if full context would exhaust this slot.
            cap = budget // max(len(chosen), 1)
            core = {ti: _excerpt(turns[ti]) for ti in hits}
            remaining = cap - sum(len(t) + 1 for t in core.values())
            for ti in indices:
                if ti not in core and len(_excerpt(turns[ti])) + 1 <= remaining:
                    core[ti] = _excerpt(turns[ti])
                    remaining -= len(core[ti]) + 1
            selected.append((si, "\n".join(core[ti] for ti in sorted(core))))
    if not selected:
        return []
    cap = budget // len(selected)
    return [{"id": sessions[si]["session_id"], "date": sessions[si]["date"], "text": text[:cap]}
            for si, text in selected]
