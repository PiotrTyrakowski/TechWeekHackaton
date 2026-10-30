"""Question-derived complementary evidence retrieval, with no gold/model access.

Simple questions retain BM25 top-k turn session IDs. Questions requesting a
comparison or aggregation can spend duplicate-turn slots on distinct sessions.
Clause anchors influence the added sessions; the maximum remains k sessions.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from retrieval import _rank, tokenize
from retrieval_specialized import _clip

METHODS = ('complementary', 'complementary-conservative')
_AGGREGATE = re.compile(r'\b(how many|how much|total|combined|average|order|earliest|latest|first|last)\b', re.I)
_SINGLE_TIME = re.compile(r'^how many (?:days|weeks|months|years) (?:ago|have passed since)\b', re.I)
_RELATION = re.compile(r'\b(between|before|after|when|since|order|earliest|latest)\b', re.I)
_GENERIC = set('day week month year time event ago passed spend spent total combined different many much order first last earliest latest current currently past recent recently new old'.split())


def _anchors(text: str) -> list[set[str]]:
    """Split only explicit coordination; prune generic time/count vocabulary.

    Each anchor has at least two content terms, avoiding a lone pronoun or
    conjunction becoming an unsupported subquery. At most four are retained.
    """
    text = re.sub(r'^.*?\bbetween\b', '', text, flags=re.I) if re.search(r'\bbetween\b', text, re.I) else text
    parts = re.split(r'\s+(?:and|or|before|after|when|since)\s+|[,;:]\s*', text, flags=re.I)
    anchors = []
    for part in parts:
        terms = set(tokenize(part)) - _GENERIC
        if len(terms) >= 2 and terms not in anchors:
            anchors.append(terms)
    return anchors[:4] if len(anchors) > 1 else []


def _choose(question, history, ranked, k, conservative):
    original = list(dict.fromkeys(si for _, si, _ in ranked[:k]))
    text = question['question']
    anchors = _anchors(text)
    broad = bool(_AGGREGATE.search(text) or (_RELATION.search(text) and anchors))
    if _SINGLE_TIME.search(text) and not anchors:
        broad = False
    if not broad or len(original) >= k:
        return original
    sessions = history['sessions']
    best = {}
    for value, si, ti in ranked:
        if si not in best:
            best[si] = (value, ti)
    pool = list(best)[:24]
    # Session representations use two strongest turns, rather than full long
    # sessions whose incidental vocabulary can swamp query-specific anchors.
    terms = {}
    for si in pool:
        hits = [ti for _, sj, ti in ranked if sj == si][:2]
        terms[si] = set(tokenize(' '.join(sessions[si]['turns'][ti]['content'] for ti in hits)))
    top = ranked[0][0]
    query = set(tokenize(text)) - _GENERIC
    df = Counter(term for si in pool for term in terms[si] & query)
    weights = {term: math.log(1 + len(pool) / (1 + df[term])) for term in query}
    chosen = original[:]
    limit = min(k, len(original) + 1) if conservative else k
    while len(chosen) < limit:
        covered = set().union(*(terms.get(si, set()) for si in chosen))
        def utility(si):
            rel = best[si][0] / top
            novel = sum(weights[t] for t in (terms[si] & query) - covered) / max(sum(weights.values()), 1e-9)
            anchor_gain = 0.0
            for anchor in anchors:
                before = max((len(anchor & terms.get(sj, set())) / len(anchor) for sj in chosen), default=0)
                anchor_gain += max(0, len(anchor & terms[si]) / len(anchor) - before)
            redundancy = max((len(terms[si] & terms.get(sj, set())) / max(len(terms[si] | terms.get(sj, set())), 1) for sj in chosen), default=0)
            return .65 * rel + .4 * novel + .4 * anchor_gain - .15 * redundancy
        remaining = [si for si in pool if si not in chosen and best[si][0] >= .2 * top]
        if not remaining:
            break
        chosen.append(max(remaining, key=lambda si: (utility(si), -si)))
    return chosen


def retrieve(question: dict, history: dict, k: int = 4, method: str = 'complementary',
             budget: int = 12000) -> list[dict]:
    if method not in METHODS:
        raise ValueError(f'unknown method {method!r}; choose {METHODS}')
    if k < 1 or budget < 1:
        raise ValueError('k and budget must be positive')
    ranked = _rank({'question': question['question']}, history)
    if not ranked:
        return []
    chosen = _choose(question, history, ranked, k, method == 'complementary-conservative')[:budget]
    result = []
    for slot, si in enumerate(chosen):
        session = history['sessions'][si]
        cap = budget // len(chosen) + (slot < budget % len(chosen))
        hits = [ti for _, sj, ti in ranked if sj == si][:2]
        hit_cap = max(1, (cap - len(hits) + 1) // len(hits))
        core = {ti: _clip(f"{session['turns'][ti]['role']}: {session['turns'][ti]['content']}", question['question'], hit_cap) for ti in hits}
        remaining = cap - sum(len(t) for t in core.values()) - max(len(core) - 1, 0)
        for ti in sorted({t + offset for t in hits for offset in (-1, 1) if 0 <= t + offset < len(session['turns'])}):
            raw = f"{session['turns'][ti]['role']}: {session['turns'][ti]['content']}"
            if ti not in core and len(raw) + 1 <= remaining:
                core[ti] = raw
                remaining -= len(raw) + 1
        result.append({'id': session['session_id'], 'date': session['date'], 'text': '\n'.join(core[ti] for ti in sorted(core))[:cap]})
    return result
