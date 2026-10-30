"""Conservative, offline citation attribution for original retrieved evidence.

This module never generates or changes a Reactor answer. It verifies a deliberately
small set of direct fact grammars: personal names, explicit completed/read/visited
item lists, and explicitly targeted assistant recommendations. Arithmetic, temporal
updates, free-form synthesis, yes/no answers and unsupported question forms remain
unresolved. Full answer-claim coverage is required before adding any fallback.

Public API: attribute_answer(question, history, evidence, result) -> JSON dict.
Citation lists contain session IDs. reactor_citation_records preserves the supplied
records verbatim; callers must also archive the separate raw Reactor result.
Support start/end are Python character offsets into evidence[evidence_index]['text']
(end exclusive). Every span is additionally matched against an original same-role
turn in that history session. No gold, model, filesystem or network access occurs.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
import unicodedata

POLICY_VERSION = "verified-direct-v1"
_LABEL = re.compile(r"\[\s*E\d+(?:\s*[,;]\s*E\d+)*\s*\]")
_ROLE = re.compile(r"(?m)^(user|assistant):[ \t]*")
_RISK = re.compile(
    r"\b(?:not|no|never|neither|nor|maybe|perhaps|might|could|would|should|if|unless|"
    r"formerly|previously|renamed|changed|instead|hypothetical|fictional|example|suppose|"
    r"may|will|pretend|imagine|guess|believe|think|hope|wish|said|says|"
    r"incorrect|false|joking|kidding)\b|n['’]t\b|\bused to\b", re.I)
_RETRACT = re.compile(r"\b(?:not true|was joking|just kidding|made (?:it|that) up|"
                      r"ignore (?:that|the above)|hypothetical|fictional|example)\b", re.I)
_TEMPORAL = re.compile(r"\b(?:latest|current|now|before|after|ago|since|formerly|"
                       r"previous|when|total|difference)\b|\b(?:how many|how long|as of|used to)\b", re.I)
_UNSAFE_ANSWER = re.compile(r"\b(?:or|maybe|perhaps|probably|possibly|not|never|either|"
                            r"because|therefore|instead)\b|n['’]t\b|[?!]", re.I)
_INTRO = re.compile(r"^(?:(?:by the way|for reference|also|actually),?\s*)*$", re.I)
_ITEM = r"[\w][\w '’\-]{0,79}"


def _norm(text):
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return " ".join(text.strip(" \t\r\n.\"'“”").split())


def _items(text):
    parts = re.split(r"\s*(?:[,;\n]|\band\b)\s*", text.strip(), flags=re.I)
    parts = [p.strip(" .\t\r\n\"“”") for p in parts if p.strip(" .\t\r\n\"“”")]
    if not parts or len(parts) > 12 or any(not re.fullmatch(_ITEM, p) for p in parts):
        return None
    if len({_norm(p) for p in parts}) != len(parts):
        return None
    return parts


def _question_plan(question, answer):
    """Parse narrow relation grammars; no semantic guesses or gold routing."""
    q = question.strip().rstrip("?").strip().replace("’", "'")
    if _TEMPORAL.search(q) or _UNSAFE_ANSWER.search(answer):
        return None
    m = re.fullmatch(r"what (?:is|['’]s) (?:the )?name of my ([\w -]+)", q, re.I)
    if not m:
        m = re.fullmatch(r"what is my ([\w -]+)'s name", q, re.I)
    if m:
        entity = _norm(m[1])
        if any(t in entity.split() for t in ("and", "or", "his", "her", "their")):
            return None
        value = answer.strip().strip(" .")
        expanded = re.fullmatch(
            rf"(?:my|your) {re.escape(entity)}['’]s name is (.+)", value, re.I)
        if expanded:
            value = expanded[1]
        if not re.fullmatch(_ITEM, value) or re.search(r"\band\b", value, re.I):
            return None
        return [{"claim": answer, "kind": "name", "key": entity, "value": value, "role": "user"}]
    m = re.fullmatch(r"what are (?:the )?names of my ([\w ,'’-]+)", q, re.I)
    if m:
        entities = [_norm(e.removeprefix("my ")) for e in re.split(r",\s*|\s+and\s+", m[1])]
        if len(entities) < 2 or len(entities) > 4 or len(set(entities)) != len(entities):
            return None
        # Explicit entity:value pairs avoid guessing which short name belongs to whom.
        pieces = re.split(r"\s*;\s*|\n+", answer.strip(" ."))
        claims = []
        for piece in pieces:
            pair = re.fullmatch(r"([\w -]+):\s*(.+)", piece)
            if not pair or _norm(pair[1]) not in entities or not re.fullmatch(_ITEM, pair[2]):
                return None
            claims.append({"claim": piece, "kind": "name", "key": _norm(pair[1]),
                           "value": pair[2], "role": "user"})
        if sorted(c["key"] for c in claims) != sorted(entities):
            return None
        return claims
    m = re.fullmatch(r"(?:what|which) (courses|books|cities|countries|museums) "
                     r"have I (completed|read|visited)", q, re.I)
    if m:
        category, verb = m[1].lower(), m[2].lower()
        compatible = {"courses": "completed", "books": "read", "cities": "visited",
                      "countries": "visited", "museums": "visited"}
        if compatible[category] != verb:
            return None
        values = _items(answer)
        if not values:
            return None
        singular = {"courses": "course", "books": "book", "cities": "city",
                    "countries": "country", "museums": "museum"}[category]
        return [{"claim": v, "kind": "item", "key": singular, "verb": verb,
                 "value": v, "role": "user"} for v in values]
    m = re.fullmatch(r"what did (?:the )?assistant recommend for ([\w '’-]+)", q, re.I)
    if m and re.fullmatch(_ITEM, answer.strip(" .")):
        target = re.sub(r"^my\b", "your", _norm(m[1]))
        return [{"claim": answer, "kind": "recommendation", "key": target,
                 "value": answer.strip(" ."), "role": "assistant"}]
    return None


def _sentences(text, start, end):
    """Sentence ranges retain exact offsets, including apostrophes in facts."""
    for match in re.finditer(r"[^.!?\n;]+[.!?;]?", text[start:end]):
        left, right = start + match.start(), start + match.end()
        while left < right and text[left].isspace():
            left += 1
        if left < right:
            yield left, right


def _date(value):
    if not isinstance(value, str):
        return None
    m = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})(?: \([A-Za-z]{3}\))?(?: (\d{2}):(\d{2}))?$", value)
    if not m:
        return None
    try:
        return datetime(*(int(v) for v in m.groups()[:3]),
                        int(m[4] or 0), int(m[5] or 0))
    except ValueError:
        return None


def _valid_evidence(history, evidence, question):
    sessions = {s.get("session_id"): s for s in history.get("sessions", []) if isinstance(s, dict)}
    valid = []
    for index, passage in enumerate(evidence):
        if not isinstance(passage, dict):
            continue
        sid, text = passage.get("id"), passage.get("text")
        session = sessions.get(sid)
        if not isinstance(sid, str) or not sid.startswith("s_") or not session or not isinstance(text, str):
            continue
        if passage.get("date") is not None and passage["date"] != session.get("date"):
            continue
        source_date, question_date = _date(session.get("date")), _date(question.get("question_date"))
        if source_date and question_date and source_date > question_date:
            continue
        valid.append((index, passage, session))
    return valid


def _assertions(claim, text, left, right):
    key = re.escape(claim["key"])
    if claim["kind"] == "name":
        patterns = [rf"my {key}['’]s name is (?P<value>{_ITEM})",
                    rf"my {key} is (?:named|called) (?P<value>{_ITEM})"]
    elif claim["kind"] == "item":
        patterns = [rf"I (?:have )?{claim['verb']} (?:the )?{key} (?P<value>{_ITEM})"]
    else:
        patterns = [rf"for {key}, I recommend (?P<value>{_ITEM})"]
    sentence = text[left:right]
    for pattern in patterns:
        for match in re.finditer(pattern, sentence, re.I):
            # Prevent borrowing a nested quote, another speaker's report, or condition.
            if not _INTRO.fullmatch(sentence[:match.start()].strip()):
                continue
            value = match["value"].strip()
            # A comma, sentence boundary, or conjunction ends the limited name grammar.
            # Conjunction tails are not names; strip only the explicitly recognized
            # pronoun continuation used by ordinary personal statements.
            if claim["kind"] == "name":
                continuation = re.search(r"\s+and\s+(?:he|she|it|they)\b", value, re.I)
                if continuation:
                    value = value[:continuation.start()]
            yield value, left + match.start(), left + match.start("value") + len(value)


def _original_context_supports(claim, span, originals):
    """A substring is insufficient: recheck the uncropped original assertion."""
    verified, observed = False, set()
    for original in originals:
        if span not in original or _RETRACT.search(original):
            continue
        for left, right in _sentences(original, 0, len(original)):
            sentence = original[left:right]
            for value, start, end in _assertions(claim, original, left, right):
                if _RISK.search(sentence):
                    if original[start:end] == span:
                        return False
                    continue
                observed.add(_norm(value))
                if original[start:end] == span and _norm(value) == _norm(claim["value"]):
                    verified = True
    return verified and (claim["kind"] == "item" or len(observed) == 1)


def _mapped_final_citations(answer, evidence):
    """Mirror the pinned official mapper, without importing a network client."""
    groups = re.findall(r"\[([^\[\]]*)\]", answer)
    labels = sorted({int(n) for group in groups for n in re.findall(r"\bE(\d+)\b", group)})
    known, unknown = [], []
    for label in labels:
        if 1 <= label <= len(evidence):
            passage = evidence[label - 1]
            known.append({"label": f"E{label}", "id": passage.get("id") if isinstance(passage, dict) else None})
        else:
            unknown.append(f"E{label}")
    return known, unknown


def _verify(claim, candidates):
    supports, observed = [], set()
    ambiguous = False
    for index, passage, session in candidates:
        text = passage["text"]
        roles = list(_ROLE.finditer(text))
        for n, role_match in enumerate(roles):
            if role_match[1] != claim["role"]:
                continue
            turn_end = roles[n + 1].start() if n + 1 < len(roles) else len(text)
            turn_text = text[role_match.end():turn_end]
            original_turns = [t.get("content", "") for t in session.get("turns", [])
                              if t.get("role") == claim["role"] and isinstance(t.get("content"), str)]
            if _RETRACT.search(turn_text):
                ambiguous = True
                continue
            for left, right in _sentences(text, role_match.end(), turn_end):
                sentence = text[left:right]
                for value, start, end in _assertions(claim, text, left, right):
                    span = text[start:end]
                    # Span, relation and value must all be original; not just the name token.
                    if not _original_context_supports(claim, span, original_turns):
                        continue
                    if _RISK.search(sentence):
                        ambiguous = True
                        continue
                    observed.add(_norm(value))
                    if _norm(value) != _norm(claim["value"]):
                        continue
                    supports.append({"claim": claim["claim"], "source_id": passage["id"],
                                     "evidence_index": index, "role": claim["role"],
                                     "span": span, "start": start, "end": end,
                                     "rule": f"direct_{claim['kind']}_v1"})
    if ambiguous or (claim["kind"] != "item" and len(observed) > 1):
        return [], "ambiguous_or_negated_source"
    if not supports:
        return [], "no_verified_direct_support"
    # One verified occurrence suffices per atomic claim, independent of retrieval rank.
    # Prefer already supplied sources in the caller when choosing the minimal union.
    return supports, None


def attribute_answer(question: dict, history: dict, evidence: list, result: dict) -> dict:
    """Return provenance only; never mutate inputs or rewrite Reactor's words.

    New fallback is all-or-nothing over parsed answer claims. Partial direct matches
    remain in supports for audit, but unresolved claims suppress all new citations.
    Supplied records are preserved verbatim, but independently checked against
    labels in result.answer. Metadata disagreement rejects citation finalization.
    Valid official citations remain even if unsupported by the narrow fallback
    grammars; invalid source/label mappings are excluded and flagged.
    """
    records = deepcopy(result.get("citations") or [])
    reactor_ids = []
    for record in records:
        sid = record.get("id") if isinstance(record, dict) else record
        if isinstance(sid, str) and sid not in reactor_ids:
            reactor_ids.append(sid)
    output = {"policy_version": POLICY_VERSION, "reactor_citations": reactor_ids,
              "reactor_citation_records": records, "fallback_citations": [],
              "unresolved_claims": [], "supports": [], "final_citations": []}
    answer = result.get("answer")
    if question.get("history_id") != history.get("history_id") or not question.get("history_id"):
        output["unresolved_claims"].append({"claim": answer or "", "reason": "history_mismatch"})
        return output
    candidates = _valid_evidence(history, evidence, question)
    valid_indices = {index: passage["id"] for index, passage, _ in candidates}
    valid_ids = set(valid_indices.values())
    mapped, unknown = _mapped_final_citations(answer if isinstance(answer, str) else "", evidence)
    supplied = [{"label": r.get("label"), "id": r.get("id")} if isinstance(r, dict) else r for r in records]
    metadata_matches = supplied == mapped and (result.get("unknown_citations") or []) == unknown
    if not metadata_matches:
        output["unresolved_claims"].append({"claim": answer or "", "reason": "citation_metadata_mismatch"})
    if unknown:
        output["unresolved_claims"].append({"claim": answer or "", "reason": "unknown_final_citation"})
    for record in records:
        sid = record.get("id") if isinstance(record, dict) else record
        label = record.get("label") if isinstance(record, dict) else None
        label_matches = True
        if label is not None:
            match = re.fullmatch(r"E([1-9]\d*)", str(label))
            label_matches = bool(match and valid_indices.get(int(match[1]) - 1) == sid)
        if not isinstance(sid, str) or sid not in valid_ids or not label_matches:
            output["unresolved_claims"].append({"claim": str(sid), "reason": "invalid_reactor_citation"})
        elif metadata_matches and sid not in output["final_citations"]:
            output["final_citations"].append(sid)
    if result.get("status") != "answered" or not isinstance(answer, str) or not answer.strip():
        output["unresolved_claims"].append({"claim": answer or "", "reason": "not_answered"})
        return output
    if (result.get("question_id") is not None and question.get("question_id") is not None
            and result["question_id"] != question["question_id"]):
        output["unresolved_claims"].append({"claim": answer, "reason": "question_mismatch"})
        return output
    if result.get("abstained") or re.match(r"^\W*INSUFFICIENT_EVIDENCE\b", answer, re.I):
        # The official adapter drops citations on semantic abstention. Keep the
        # supplied records above for provenance, but finalize no citation IDs.
        output["final_citations"] = []
        return output
    clean_answer = _LABEL.sub("", answer).strip()
    claims = _question_plan(question.get("question", ""), clean_answer)
    if not claims:
        output["unresolved_claims"].append({"claim": clean_answer, "reason": "unsupported_question_or_answer_form"})
        return output
    matches = []
    for claim in claims:
        found, reason = _verify(claim, candidates)
        if reason:
            output["unresolved_claims"].append({"claim": claim["claim"], "reason": reason})
        elif found:
            # Reuse a supplied source when it verifies this claim; otherwise take
            # stable evidence order, after verification rather than blind ranking.
            support = min(found, key=lambda s: (s["source_id"] not in output["final_citations"],
                                                s["evidence_index"], s["start"]))
            matches.append(support)
    output["supports"] = matches
    if not output["unresolved_claims"]:
        for support in matches:
            sid = support["source_id"]
            if sid not in output["final_citations"]:
                output["fallback_citations"].append(sid)
                output["final_citations"].append(sid)
    return output
