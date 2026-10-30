"""Offline, gold-free question routing with distinct-session coverage.

``session`` allocates k distinct sessions; ``adaptive`` allocates 2*k for
count/aggregation/chronology/update wording and k otherwise. Scores and dates
come only from the supplied history. Temporal wording never boosts recency:
historical comparisons need both old and new evidence.
"""
from __future__ import annotations

import re

from retrieval import _rank, tokenize

METHODS = ("session", "adaptive")
_BROAD = re.compile(
    r"\b(how many|how much|total|altogether|combined|each|all (?:the |my )?|"
    r"between|first|last|before|after|ago|passed|since|order|currently|"
    r"recent|latest|updated?|changed?|still|now)\b", re.I)


def _clip(text: str, question: str, cap: int) -> str:
    """Keep the role and center long content around the strongest query span."""
    if len(text) <= cap:
        return text
    if cap < 12:
        return text[:cap]
    role, _, content = text.partition(": ")
    prefix = role + ": "
    room = cap - len(prefix)
    if room <= 0:
        return text[:cap]
    query = set(tokenize(question))
    hits = [(m.start(), m.end()) for m in re.finditer(r"[^\W_]+", content)
            if set(tokenize(m.group())) & query]
    if not hits:
        return text[:cap]
    # Maximize query matches inside one contiguous excerpt, with stable ties.
    best = max(hits, key=lambda h: sum(h[0] <= p[0] < h[0] + room for p in hits))
    start = max(0, min(best[0] - room // 5, len(content) - room))
    return prefix + content[start:start + room]


def retrieve(question: dict, history: dict, k: int = 4, method: str = "adaptive",
             budget: int = 12000) -> list[dict]:
    """Return role-tagged passages with valid history-local IDs and dates."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; choose {METHODS}")
    if k < 1 or budget < 1:
        raise ValueError("k and budget must be positive")
    ranked = _rank(question, history)
    count = k * (2 if method == "adaptive" and _BROAD.search(question["question"]) else 1)
    chosen = list(dict.fromkeys(si for _, si, _ in ranked))[:min(count, budget)]
    if not chosen:
        return []
    output = []
    for slot, si in enumerate(chosen):
        session = history["sessions"][si]
        turns = session["turns"]
        cap = budget // len(chosen) + (slot < budget % len(chosen))
        hits = [ti for _, sj, ti in ranked if sj == si][:2]
        # Share space between two best hits; only then add adjacent dialogue.
        core = {}
        hit_cap = max(1, (cap - max(0, len(hits) - 1)) // len(hits))
        for ti in hits:
            raw = f"{turns[ti]['role']}: {turns[ti]['content']}"
            core[ti] = _clip(raw, question["question"], min(hit_cap, cap))
        text = "\n".join(core[ti] for ti in sorted(core))[:cap]
        remaining = cap - len(text)
        for ti in sorted({n for t in hits for n in (t - 1, t + 1)
                          if 0 <= n < len(turns)}):
            raw = f"{turns[ti]['role']}: {turns[ti]['content']}"
            if ti not in core and len(raw) + 1 <= remaining:
                core[ti] = raw
                remaining -= len(raw) + 1
        output.append({"id": session["session_id"], "date": session["date"],
                       "text": "\n".join(core[ti] for ti in sorted(core))[:cap]})
    return output
