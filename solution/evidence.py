"""From a question and its history to the message Reactor sees: query analysis, turn selection, date help."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np

from retrieval import HistoryIndex, tokens

MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?"
_ISO = re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")
_MDY = re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,\s*|\s+)(20\d\d)\b", re.I)
_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON},?\s+(20\d\d)\b", re.I)
_MD = re.compile(rf"\b(?:on|since|by|until|from|before|after)\s+(?:the\s+)?{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!,?\s*20\d\d)", re.I)
_RELATIVE = {"today": 0, "this morning": 0, "this afternoon": 0, "this evening": 0, "tonight": 0,
             "yesterday": -1, "last night": -1, "tomorrow": 1, "the day before yesterday": -2}
_REL = re.compile(r"\b(the day before yesterday|today|this morning|this afternoon|this evening|tonight|yesterday|"
                  r"last night|tomorrow)\b", re.I)
_AGO = re.compile(r"\b(a|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(day|week)s?\s+ago\b", re.I)
_NUM = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10}


def parse_date(value: str) -> datetime:
    """The benchmark's '2023/05/20 (Sat) 02:21'."""
    return datetime.strptime(value[:10] + value[-6:], "%Y/%m/%d %H:%M") if "(" in value else \
        datetime.strptime(value[:10], "%Y/%m/%d")


def find_dates(text: str, today: date) -> list[tuple[int, int, date, str]]:
    """(start, end, date, kind) for explicit and relative dates in ``text``; relative ones resolved against ``today``."""

    out = []
    for rx, order in ((_ISO, "ymd"), (_MDY, "mdy"), (_DMY, "dmy")):
        for m in rx.finditer(text):
            try:
                if order == "ymd":
                    d = date(int(m[1]), int(m[2]), int(m[3]))
                elif order == "mdy":
                    d = date(int(m[3]), MONTHS[m[1].lower()], int(m[2]))
                else:
                    d = date(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
            except (ValueError, KeyError):
                continue
            out.append((m.start(), m.end(), d, "explicit"))
    for m in _MD.finditer(text):
        try:
            d = date(today.year, MONTHS[m[1].lower()], int(m[2]))
        except (ValueError, KeyError):
            continue
        if d > today + timedelta(days=200):
            d = d.replace(year=d.year - 1)
        out.append((m.start(), m.end(), d, "inferred-year"))
    for m in _REL.finditer(text):
        out.append((m.start(), m.end(), today + timedelta(days=_RELATIVE[m[1].lower()]), "relative"))
    for m in _AGO.finditer(text):
        n = int(m[1]) if m[1].isdigit() else _NUM[m[1].lower()]
        out.append((m.start(), m.end(), today - timedelta(days=n * (7 if m[2].lower() == "week" else 1)), "relative"))
    out.sort()
    keep, last = [], -1
    for item in out:  # drop overlaps, first wins
        if item[0] >= last:
            keep.append(item)
            last = item[1]
    return keep


def annotate_dates(text: str, today: date) -> str:
    """Relative and non-ISO dates get their calendar date in brackets: 'yesterday [2023-05-19]'."""

    pieces, pos = [], 0
    for start, end, d, kind in find_dates(text, today):
        pieces.append(text[pos:end])
        if kind != "explicit" or not _ISO.fullmatch(text[start:end]):
            pieces.append(f" [{d.isoformat()}]")
        pos = end
    pieces.append(text[pos:])
    return "".join(pieces)


@dataclass
class Plan:
    kind: str  # "between", "temporal", "update", "count", "recommend", "fact"
    queries: list[str]
    events: list[str] = field(default_factory=list)


_BETWEEN = [
    re.compile(r"how many (days|weeks|months) (?:apart )?(?:were|was|passed between|are|is there between|between)\s+(.+?)\s+and\s+(.+?)\??$", re.I),
    re.compile(r"how many (days|weeks|months) (?:after|before)\s+(.+?)\s+(?:did|was|were|do|is|had)\s+(.+?)\??$", re.I),
    re.compile(r"how many (days|weeks|months) (?:passed |elapsed )?(?:after|before|between|since)\s+(.+?)\s+(?:and|until|when)\s+(.+?)\??$", re.I),
]
_ORDER = re.compile(r"\b(?:first|earlier|before|sooner|last|later)\b[^,:?]*[,:]\s*(?:the\s+)?(.+?)\s+or\s+(?:the\s+)?(.+?)\??$",
                    re.I)
_FILLER = re.compile(r"\b(i forgot|i lost track|the name|again)\b[.!]?", re.I)


def plan(question: str) -> Plan:
    q = _FILLER.sub("", question).strip()
    q = re.sub(r"\s*\?.*$", "?", q) if "?" in q else q
    for rx in _BETWEEN:
        m = rx.search(q)
        if m:
            a, b = m[2].strip(" ?"), m[3].strip(" ?")
            return Plan("between", [question, a, b], [a, b])
    m = _ORDER.search(q)
    if m:
        a, b = m[1].strip(" ?,"), m[2].strip(" ?,")
        return Plan("between", [question, a, b], [a, b])
    low = q.lower()
    if re.search(r"\b(how many (days|weeks|months|years)|how long|when did|what date|which .* first|what day)\b", low):
        return Plan("temporal", [question])
    if re.search(r"\b(you|did you) (recommend|suggest|mention|told|tell|said)|\bthat .* you\b", low):
        return Plan("recommend", [question])
    if re.search(r"\b(now|currently|current|these days|end up|ended up|anymore|latest|last .*mentioned|most recent|so far|right now)\b", low):
        return Plan("update", [question])
    if re.search(r"\b(how many|how much|total|in total|combined|altogether)\b", low):
        return Plan("count", [question])
    return Plan("fact", [question])


@dataclass
class Picked:
    session: int
    turn: int
    score: float
    chunk_text: str


def pick_turns(index: HistoryIndex, scores: list[np.ndarray], budget_turns: int) -> list[Picked]:
    """Round-robin over each query's ranking of turns (best chunk per turn), without repeats."""

    rankings = []
    for cs in scores:
        best: dict[tuple[int, int], tuple[float, int]] = {}
        for ci in np.argsort(-cs):
            c = index.chunks[ci]
            key = (c.session, c.turn)
            if key not in best:
                best[key] = (float(cs[ci]), int(ci))
            if len(best) >= budget_turns * 3:
                break
        rankings.append(sorted(best.items(), key=lambda kv: -kv[1][0]))
    picked, seen = [], set()
    pos = [0] * len(rankings)
    while len(picked) < budget_turns and any(p < len(r) for p, r in zip(pos, rankings)):
        for qi, ranking in enumerate(rankings):
            while pos[qi] < len(ranking) and ranking[pos[qi]][0] in seen:
                pos[qi] += 1
            if pos[qi] < len(ranking):
                (si, ti), (score, ci) = ranking[pos[qi]]
                seen.add((si, ti))
                picked.append(Picked(si, ti, score, index.chunks[ci].text))
                pos[qi] += 1
            if len(picked) >= budget_turns:
                break
    return picked


def clip(text: str, limit: int, around: str | None = None) -> str:
    if len(text) <= limit:
        return text
    if around and around in text:
        start = text.index(around)
        lo = max(0, start - (limit - len(around)) // 2)
        lo = text.rfind(" ", 0, lo) + 1 if lo else 0
        return ("..." if lo else "") + text[lo:lo + limit].rstrip() + "..."
    return text[:limit].rstrip() + "..."


TURNS = {"recommend": 10, "fact": 7, "update": 6, "count": 5, "between": 6, "temporal": 8}
SENTS = {"recommend": 25, "fact": 35, "update": 50, "count": 70, "between": 45, "temporal": 45}


def ranked_sentences(index: HistoryIndex, sscores: list[np.ndarray], n: int) -> list[int]:
    """Round-robin over each query's sentence ranking, without repeats."""

    orders = [list(np.argsort(-sc)[: n * 2]) for sc in sscores]
    out, seen = [], set()
    for rank in range(n * 2):
        for order in orders:
            if rank < len(order) and order[rank] not in seen:
                seen.add(order[rank])
                out.append(int(order[rank]))
        if len(out) >= n:
            break
    return out[:n]


def best_sentence(text: str, quote: str) -> str | None:
    """The sentence of `text` that shares the most words with `quote`, to clip around."""

    q = set(tokens(quote))
    pieces = [x for x in re.split(r"(?<=[.!?])\s+|\n+", text) if x.strip()]  # exact substrings, unlike split_sentences
    return max(pieces, key=lambda x: len(q & set(tokens(x)))) if q and pieces else None


def build(question: dict, index: HistoryIndex, embedder=None, budget: int = 22000, w_dense: float = 1.0,
          w_bm25: float = 0.5, reranker=None, must: list[tuple[int, int, str]] | None = None
          ) -> tuple[str, list[dict], dict]:
    """(question text with guidance, excerpts for client.py, debug info).

    Evidence is the turns in `must` (from scan.py's whole-history read, clipped around their quote), then the best few
    whole turns plus the best sentences of the history (each with its neighbours when the budget allows), grouped by
    session and sorted by date."""

    p = plan(question["question"])
    qdate = parse_date(question["question_date"])
    qvecs = [embedder.query(q) if embedder is not None else None for q in p.queries]
    scores = [index.chunk_scores(q, v, w_dense=w_dense, w_bm25=w_bm25) for q, v in zip(p.queries, qvecs)]
    sscores = [index.sentence_scores(q, v, w_dense=w_dense, w_bm25=w_bm25) for q, v in zip(p.queries, qvecs)]
    if reranker is not None:
        scores = [index.rerank(reranker, q, sc, "chunks", keep=60) for q, sc in zip(p.queries, scores)]
        sscores = [index.rerank(reranker, q, sc, "sents", keep=400, user_all=True) for q, sc in zip(p.queries, sscores)]
    picked = pick_turns(index, scores, TURNS[p.kind])
    sessions = index.sessions

    full: dict[tuple[int, int], str] = {}  # whole (clipped) turns
    extra: dict[tuple[int, int], str] = {}  # the user question before an assistant turn
    chosen: dict[tuple[int, int], set[int]] = {}  # sentence positions within a turn
    used = 0
    for si, ti, quote in must or []:
        turns = sessions[si]["turns"]
        turn = turns[ti]
        text = clip(turn["content"], 600, best_sentence(turn["content"], quote))
        cost = len(text)
        if turn["role"] == "assistant" and ti > 0 and (si, ti - 1) not in full:
            prev = clip(turns[ti - 1]["content"], 250)
            extra[(si, ti - 1)] = prev
            cost += len(prev)
        if used + cost > budget * 0.4:
            break
        full[(si, ti)] = text
        used += cost
    for pk in picked:
        if (pk.session, pk.turn) in full:
            continue
        turns = sessions[pk.session]["turns"]
        turn = turns[pk.turn]
        text = clip(turn["content"], 1500 if turn["role"] == "user" else 1300, pk.chunk_text[:200])
        cost = len(text)
        if turn["role"] == "assistant" and pk.turn > 0 and (pk.session, pk.turn - 1) not in full:
            prev = clip(turns[pk.turn - 1]["content"], 400)
            extra[(pk.session, pk.turn - 1)] = prev
            cost += len(prev)
        if used + cost > budget * 0.45:
            break
        full[(pk.session, pk.turn)] = text
        used += cost

    by_turn: dict[tuple[int, int], list[int]] = {}
    for gi, sent in enumerate(index.sents):
        by_turn.setdefault((sent.session, sent.turn), []).append(gi)
    top_sents = [gi for gi in ranked_sentences(index, sscores, SENTS[p.kind])
                 if (index.sents[gi].session, index.sents[gi].turn) not in full]
    for gi in top_sents:  # the sentences first, then their neighbours
        sent = index.sents[gi]
        cost = len(sent.text) + 4
        if used + cost > budget:
            break
        chosen.setdefault((sent.session, sent.turn), set()).add(sent.index)
        used += cost
    for gi in top_sents:
        sent = index.sents[gi]
        key = (sent.session, sent.turn)
        if sent.index not in chosen.get(key, ()):
            continue
        for k in (sent.index - 1, sent.index + 1):
            if 0 <= k < len(by_turn[key]) and k not in chosen[key]:
                cost = min(len(index.sents[by_turn[key][k]].text), 240) + 4
                if used + cost <= budget:
                    chosen[key].add(k)
                    used += cost

    per_session: dict[int, dict[int, str]] = {}
    for (si, ti), text in extra.items():
        per_session.setdefault(si, {})[ti] = f"user: {text}"
    for (si, ti), text in full.items():
        per_session.setdefault(si, {})[ti] = f"{sessions[si]['turns'][ti]['role']}: {text}"
    for (si, ti), ks in chosen.items():
        if ti in per_session.get(si, {}):
            continue
        parts, last = [], None
        for k in sorted(ks):
            if last is not None and k != last + 1:
                parts.append("...")
            t = index.sents[by_turn[(si, ti)][k]].text
            parts.append(t if len(t) <= 240 or k in {index.sents[g].index for g in top_sents
                                                      if (index.sents[g].session, index.sents[g].turn) == (si, ti)}
                         else t[:240] + "...")
            last = k
        lead = "" if min(ks) == 0 else "... "
        tail = "" if max(ks) == len(by_turn[(si, ti)]) - 1 else " ..."
        per_session.setdefault(si, {})[ti] = f"{sessions[si]['turns'][ti]['role']}: {lead}{' '.join(parts)}{tail}"

    excerpts = []
    for si in sorted(per_session, key=lambda i: (parse_date(sessions[i]["date"]), i)):
        session = sessions[si]
        sdate = parse_date(session["date"])
        ago = (qdate.date() - sdate.date()).days
        lines, last = [], None
        for ti in sorted(per_session[si]):
            if last is not None and ti != last + 1:
                lines.append("[...]")
            lines.append(annotate_dates(per_session[si][ti], sdate.date()))
            last = ti
        excerpts.append({"id": session["session_id"],
                         "date": f"{session['date']}, {ago} days before the question date",
                         "text": "\n".join(lines)})

    table = date_table(p, excerpts, qdate.date(), index, scores)
    top = sessions[picked[0].session]["session_id"] if picked else None
    text = compose(question["question"], p.kind, table)
    return text, excerpts, {"kind": p.kind, "queries": p.queries, "chars": used, "top": top, "table": table,
                            "must": len(must or [])}


def compose(question: str, kind: str, table: list[str]) -> str:
    return question.strip() + "\n\n" + guidance_for(kind, table)


def guidance_for(kind: str, table: list[str]) -> str:
    """What the retrieval system tells Reactor about the evidence and the answer format, by question kind."""

    lines = ["How to answer (from the system that retrieved the evidence):",
             "- The evidence is excerpts from my past chats with you, oldest first, each with its date. Some "
             "excerpts are near-misses: similar things that happened to someone else (a friend, partner, relative, "
             "neighbour, colleague) or a different item, place or event. Use only what is about me and exactly what "
             "the question asks.",
             "- Things change: when the evidence gives different values at different times, the most recent one "
             "(latest date) is the current one, unless the question asks about an earlier time. A later message "
             "that changes it counts even when it is worded as a plan or just-made decision (\"I'm moving them to "
             "...\", \"now booked for ...\"): answer with the newer value unless a still later message undoes it.",
             "- Some questions need facts from several excerpts combined: a total, a difference (such as how much "
             "is still needed), or which came first.",
             "- Relative dates are already resolved in brackets, e.g. 'yesterday [2023-05-19]'."]
    if kind in ("between", "temporal"):
        lines.append("- For the date of an event, use the date stated in the text; if none is stated, the event "
                     "happened on the excerpt's date.")
        if table:
            lines.append("- Precomputed by the retrieval system, may include near-misses (check each candidate is "
                         "really the event asked about, and that it is mine): candidate dates for each event and the "
                         "day differences between them (use these instead of doing the arithmetic yourself):")
            lines += table
    if kind == "count":
        lines.append("- For counts and totals: before the final answer line, list every qualifying item, one per "
                     "line with its excerpt label; include each thing I said I have, did, bought, ordered or use that "
                     "fits the question (whose, when, which kind), taking the question's category in its everyday "
                     "broad sense (a mattress is furniture, a smartwatch is a device); count the same item mentioned "
                     "in several chats once; "
                     "then count or add them up.")
    lines += ["- The final answer line must contain only the answer itself (a name, number, date, or short phrase), "
              "with no alternatives and no explanation, followed by the labels of the excerpts it is based on, e.g. "
              "'Luna [E3]'. Cite every excerpt you used (for a count, each excerpt with a counted item; for a value "
              "that changed, the excerpts with the earlier and the latest value), but not near-misses.",
              "- Answer INSUFFICIENT_EVIDENCE only when the evidence never mentions the specific thing asked about "
              "for me. If it is mentioned but some detail is uncertain, give your best answer."]
    return "\n".join(lines)


_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def event_dates(index: HistoryIndex, event: str, ranking: np.ndarray, k_turns: int = 5) -> list[tuple[date, str, str]]:
    """(date, sentence, session_id) candidates for an event: dated sentences of the turns that best match it."""

    want = set(tokens(event))
    seen, out = set(), []
    for ci in np.argsort(-ranking):
        c = index.chunks[ci]
        if (c.session, c.turn) in seen:
            continue
        seen.add((c.session, c.turn))
        session = index.sessions[c.session]
        sdate = parse_date(session["date"]).date()
        text = session["turns"][c.turn]["content"]
        best = []
        for sent in _SENT.split(text):
            overlap = len(want & set(tokens(sent)))
            if not overlap:
                continue
            ds = find_dates(sent, sdate)
            best.append((overlap, bool(ds), sent, [d for _, _, d, _ in ds]))
        if best:
            top = max(b[0] for b in best)
            best.sort(key=lambda b: (not (b[1] and 2 * b[0] >= top), -b[0]))
            overlap, dated, sent, ds = best[0]
            if not dated:  # the event's date is the session's, unless a neighbouring sentence states one
                ds = [sdate]
            for d in ds[:2]:
                out.append((d, sent.strip()[:220], session["session_id"]))
        if len(seen) >= k_turns:
            break
    return out


def date_table(p: Plan, excerpts: list[dict], qdate: date, index: HistoryIndex | None = None,
               scores: list[np.ndarray] | None = None) -> list[str]:
    """For two-event questions: each event's candidate dates (with the sentence stating them) and the day differences
    between every pair of candidates."""

    if p.kind != "between" or index is None or not scores or len(scores) < 3:
        return []
    label = {e["id"]: f"E{n}" for n, e in enumerate(excerpts, 1)}
    cands = []
    for event, ranking in zip(p.events, scores[1:3]):
        found = [(d, sent, sid) for d, sent, sid in event_dates(index, event, ranking) if sid in label]
        cands.append(found)
    if not all(cands):
        return []
    out = []
    for name, found in zip(p.events, cands):
        out.append(f"  candidates for '{name}': " + "; ".join(
            f"{d.isoformat()} ({label[sid]}: \"{sent}\")" for d, sent, sid in found))
    pairs = sorted({(a, b) for a, _, _ in cands[0] for b, _, _ in cands[1]})
    out.append("  day differences: " + "; ".join(f"{a.isoformat()} to {b.isoformat()} = {abs((b - a).days)} days"
                                                 for a, b in pairs))
    return out
