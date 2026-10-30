"""Verbatim sentence memory with bounded, history-local lexical indexing.

Only questions and histories enter retrieval. Memory retains original role and
turn IDs. Cached content never stores session dates; dates come from this history.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from functools import lru_cache

from retrieval import tokenize

METHODS = ('memory', 'memory-facts')
_SENTENCES = re.compile(r'[^\n.!?]+(?:[.!?]+|(?=\n)|$)')
_PERSONAL = re.compile(r"\b(?:I|I'm|I've|I'd|my|mine|we|our)\b", re.I)
_QUESTION = re.compile(r'\?\s*$')
_MULTI_QUERY = re.compile(
    r'\b(how many|how much|how long|how old|how often|total|average|combined|'
    r'between|compared|than|percentage|order|earliest|before|after|both|'
    r'initially|initial|previous|currently|current|now|since|first|last|ago|'
    r'weeks|months|years)\b', re.I)


@lru_cache(maxsize=4096)
def _cards(role: str, source: str, content: str):
    """Cache immutable verbatim snippets and terms, without history metadata."""
    pieces = []
    starts = []
    for match in _SENTENCES.finditer(content):
        text = match.group().strip()
        if not text:
            continue
        # Tiny clauses have little independent meaning: join adjacent clauses.
        if len(text) < 45 and pieces:
            pieces[-1] = content[starts[-1]:match.end()].strip()
        else:
            pieces.append(text)
            starts.append(match.start())
    if not pieces:
        pieces = [content]
    return tuple((text, Counter(tokenize(text)), bool(_PERSONAL.search(text)),
                  bool(_QUESTION.search(text))) for text in pieces)


_cached_history = None
_cached_index = None


def _index(history):
    global _cached_history, _cached_index
    if history is _cached_history:
        return _cached_index
    cards = []
    postings = defaultdict(list)
    lengths = []
    for si, session in enumerate(history['sessions']):
        for ti, turn in enumerate(session['turns']):
            source = turn.get('turn_id', str(ti))
            for ci, (text, terms, personal, question) in enumerate(_cards(turn['role'], source, turn['content'])):
                idx = len(cards)
                length = sum(terms.values())
                cards.append((si, ti, ci, text, turn['role'], source, personal, question))
                lengths.append(length)
                for term, tf in terms.items():
                    postings[term].append((idx, tf))
    _cached_history = history
    _cached_index = cards, postings, lengths, sum(lengths) / max(len(lengths), 1)
    return _cached_index


def _ranking(question, history, method):
    cards, postings, lengths, avgdl = _index(history)
    scores = defaultdict(float)
    n = len(cards)
    for term in set(tokenize(question['question'])):
        hits = postings.get(term, ())
        idf = math.log(1 + (n - len(hits) + .5) / (len(hits) + .5))
        for idx, tf in hits:
            norm = 1.2 * (.25 + .75 * lengths[idx] / max(avgdl, 1))
            scores[idx] += idf * tf * 2.2 / (tf + norm)
    session_cards = defaultdict(list)
    for idx, score in scores.items():
        si, ti, ci, text, role, source, personal, is_question = cards[idx]
        if method == 'memory-facts':
            # User assertions are the compact factual memory; assistant prose is
            # still searchable for questions explicitly about recommendations.
            score *= (1.15 if role == 'user' else .75)
            if role == 'user' and personal and not is_question:
                score *= 1.2
        session_cards[si].append((score, idx))
    for hits in session_cards.values():
        hits.sort(key=lambda item: (-item[0], item[1]))
    # Support from a second distinct sentence mildly raises a session's score.
    session_scores = {si: hits[0][0] + .15 * (hits[1][0] if len(hits) > 1 else 0)
                      for si, hits in session_cards.items()}
    ranked = sorted(session_cards, key=lambda si: (-session_scores[si], si))
    return cards, session_cards, ranked, session_scores


def retrieve(question, history, k=4, method='memory', budget=12000):
    """Rank verbatim memory cards, consolidate by source session, pack top cards."""
    if method not in METHODS:
        raise ValueError(f'unknown method {method!r}; choose {METHODS}')
    if k < 1 or budget < 1:
        raise ValueError('k and budget must be positive')
    cards, session_cards, ranked, session_scores = _ranking(question, history, method)
    ranked = ranked[:k]
    if method == 'memory-facts' and ranked:
        # Development-only calibration: quantitative/time questions need more
        # evidence; ordinary fact lookup has a sharper confidence threshold.
        ratio = .55 if _MULTI_QUERY.search(question['question']) else .75
        threshold = ratio * session_scores[ranked[0]]
        ranked = [si for si in ranked if session_scores[si] >= threshold]
    if not ranked:
        return []
    cap = budget // len(ranked)
    result = []
    for si in ranked:
        hits = session_cards[si]
        selected = {}
        used = 0
        # Select at most six relevance-ranked snippets, then restore chronology.
        for _, idx in hits[:6]:
            card = cards[idx]
            line = f'{card[4]} [{card[5]}]: {card[3]}'
            if used + len(line) + 1 <= cap:
                selected[idx] = line
                used += len(line) + 1
        if not selected:
            idx = hits[0][1]
            card = cards[idx]
            selected[idx] = f'{card[4]} [{card[5]}]: {card[3]}'[:cap]
        session = history['sessions'][si]
        result.append({'id': session['session_id'], 'date': session['date'],
                       'text': '\n'.join(selected[idx] for idx in sorted(selected))[:cap]})
    return result
