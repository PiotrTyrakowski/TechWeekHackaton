"""The context layer: one new input (a voice note, a chat, a short note, a document, a correction) -> verified facts for
one of the firm's jobs, through the reader: a normal model (llm.py) or Reactor (reactor.py).

The dashboard sends the jobs as it knows them now and the job's earlier messages; the reader gets those messages as
evidence [E1]..[En-1] and the new input last, and answers one line per fact, quoting the input's own words. Our code
checks every line before it reaches a job: the quoted words must be in the input, the job must be one of the firm's,
statuses come from the fixed list, amounts and dates must parse. A line that fails is returned under "rejected", never
applied.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re

import llm
import reactor

STATUSES = ["pending", "agreed", "completed", "paid"]
STATUS_WORDS = {"pending": "awaiting the customer's decision", "agreed": "agreed, not done yet",
                "completed": "done, not paid yet", "paid": "paid"}
FACTS = ["amount", "status", "due", "start", "excludes", "budget"]
ACTIONS = ("work order", "schedule", "order parts", "follow-up")

# "amount: 4300 | "four thousand three hundred" [E7]", tolerating list markers and bold around the key.
_LINE = re.compile(r"^[ \t*\-•]*(job|" + "|".join(FACTS) + r"|reply|conflict|unknown|action)\**[ \t]*:\**[ \t]*(.*)$",
                   re.I | re.M)
_QUOTED = re.compile(r"[\"“„]([^\"“”„]+)[\"”“]")
_CITES = re.compile(r"\[\s*E\d+(?:\s*,\s*E?\d+)*\s*\]", re.I)
_UNCHANGED = re.compile(r"^\W*(unchanged|no change|not changed|same|n/?a|none)?\W*$", re.I)
_NONE = re.compile(r"^\W*(none|unchanged|n/?a|no(thing| conflict)?|-+|—)?\W*$", re.I)
_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")


class NoAnswer(Exception):
    """The reader was asked but gave no usable answer (timeout, refusal, error)."""

    def __init__(self, result: dict) -> None:
        super().__init__(f"{(result.get('reader') or 'reactor').capitalize()}: {result.get('status')} "
                         f"{result.get('code') or result.get('error') or ''}".strip())
        self.result = result


def evidence(text: str, ctx: dict) -> list[dict]:
    """The job's earlier messages, oldest first, then the new input as the last passage."""

    passages = [{"id": p.get("id", f"p{i}"), "date": p.get("date", ctx["date"]), "text": p["text"]}
                for i, p in enumerate(ctx.get("passages", []))]
    passages.append({"id": "input", "date": ctx["date"],
                     "text": f"[{ctx.get('channel', 'voice note')}, {ctx.get('author_role', 'owner')}] {text.strip()}"})
    return passages


def _job_line(j: dict) -> str:
    parts = [j["id"], j.get("customer") or "unknown customer", f"{j.get('amount', 0)} PLN",
             STATUS_WORDS.get(j.get("status"), j.get("status") or "")]
    parts += [f"{label} {j[k]}" for k, label in (("due", "contact by"), ("start", "starts"), ("budget", "budget"))
              if j.get(k)]
    if j.get("excludes"):
        parts.append("out of scope: " + ", ".join(j["excludes"]))
    return "- " + " · ".join(str(p) for p in parts)


def question(ctx: dict) -> str:
    """One question for every fact at once: one reader call per input."""

    n, jobs, job = len(ctx.get("passages", [])) + 1, ctx.get("jobs", []), ctx.get("job")
    who = {"owner": "the owner", "customer": "a customer", "worker": "the crew"}.get(ctx.get("author_role"), "the owner")
    lines = [
        "You keep the job book of a small plumbing and heating firm. Its jobs now (id · customer · price · state):",
        *[_job_line(j) for j in jobs],
        "",
        f"[E{n}] is a new {ctx.get('channel', 'voice note')} from {who}"
        + (f", about job {job}." if job else ". Work out which job it is about.")
        + f" Which facts does [E{n}] change, does it contradict anything earlier, and what should happen next?",
        "After the final-answer marker write exactly these lines and nothing else:",
    ]
    if not job:
        lines.append(f"job: <the id from the list that [E{n}] is about, or NONE if you cannot tell>")
    q = f"| \"<the exact words from [E{n}] that say it>\" [E{n}]"
    lines += [
        f"amount: <the new price in PLN, digits only> {q}",
        f"status: <one of {', '.join(STATUSES)}> {q}",
        f"due: <YYYY-MM-DD, when someone must contact the customer> {q}",
        f"start: <YYYY-MM-DD, when the work starts> {q}",
        f"excludes: <work taken out of the job, under five words> {q}",
        f"budget: <the customer's maximum in PLN, digits only> {q}",
        f"conflict: <what in [E{n}] disagrees with the job or an earlier passage, naming both> | "
        f"\"<the exact words from [E{n}]>\" [E{n}] [the earlier passage]",
        "unknown: <the most important thing this job still does not know, under ten words>",
        "action: <one of: work order, schedule, order parts, follow-up>: <the next step, under twelve words>",
        "reply: <a short message to the customer answering their latest message, using only facts from the evidence>",
        "",
        f"Write UNCHANGED for a fact [E{n}] does not change, and NONE for conflict, unknown or action when there is none. "
        "Only the owner sets a price. A customer's yes makes the job agreed only if it accepts the current price. "
        "completed means the work is finished but not paid; paid means the owner confirms the money came in. "
        f"Today is {ctx['date']}: write 'tomorrow' and weekdays as dates.",
    ]
    return "\n".join(lines)


def parse(answer: str) -> dict[str, str]:
    """Each line of the final answer by key; a key written twice keeps its last line."""

    return {m.group(1).lower(): m.group(2).strip() for m in _LINE.finditer(answer)}


def _norm(s: str) -> str:
    # Same length as s, so positions found here are positions in s.
    return s.replace("’", "'").replace("‘", "'").lower()


def locate(text: str, quoted: str) -> str | None:
    """The input's own words for ``quoted``: an exact match ignoring case and apostrophe style, else the closest run of
    words (similarity 0.85 or more). None when the input doesn't say it."""

    n, q = _norm(text), _norm(quoted).strip(" .,;!?")
    if not q:
        return None
    at = n.find(q)
    if at >= 0:
        return text[at:at + len(q)]
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    k, best, span = len(q.split()), 0.0, None
    for size in range(max(1, k - 2), k + 3):
        for i in range(len(words) - size + 1):
            a, b = words[i][0], words[i + size - 1][1]
            score = difflib.SequenceMatcher(None, n[a:b].strip(" .,;!?"), q).ratio()
            if score > best:
                best, span = score, (a, b)
    return text[span[0]:span[1]].strip(" .,;!?") if span and best >= 0.85 else None


def _number(v: str) -> int | None:
    m = re.search(r"(\d[\d, ]*(?:\.\d+)?)\s*(k\b)?", v.lower())
    if not m:
        return None
    n = float(m.group(1).replace(",", "").replace(" ", ""))
    return round(n * (1000 if m.group(2) else 1)) or None


def value(key: str, v: str) -> object | None:
    """The fact in the form the dashboard's engine uses, or None when it doesn't parse."""

    v = _CITES.sub("", v).strip().strip("\"“”„").strip().rstrip(".")
    if key in ("amount", "budget"):
        return _number(v)
    if key == "status":
        low = v.lower()
        return next((s for s in STATUSES if s in low), None)
    if key in ("due", "start"):
        m = _DATE.search(v)
        return m.group(1) if m else None
    return v[:60] or None


def facts(answer: str, text: str) -> tuple[dict, dict, list[dict]]:
    """``(facts, quotes, rejected)`` from the final answer: each fact with the input's words that say it."""

    lines, found, quotes, rejected = parse(answer), {}, {}, []
    for key in FACTS:
        line = lines.get(key)
        if line is None:
            continue
        raw, bar, rest = line.partition("|")
        if not bar:  # no "|": the quote, if any, follows the value
            m = _QUOTED.search(line)
            raw, rest = (line[:m.start()], line[m.start():]) if m else (line, "")
        if _UNCHANGED.match(_CITES.sub("", raw)):
            continue
        m = _QUOTED.search(rest)
        phrase = locate(text, m.group(1)) if m else None
        v = value(key, raw)
        if v is None:
            rejected.append({"key": key, "value": raw.strip(), "reason": "not a value this field takes"})
        elif not phrase:
            rejected.append({"key": key, "value": v, "quoted": m.group(1) if m else None,
                             "reason": "the quoted words are not in the input"})
        else:
            found[key], quotes[key] = v, phrase
    return found, quotes, rejected


def job(answer: str, ctx: dict) -> str | None:
    """The job the input is about: the one the sender picked, else the reader's pick if it is one of the firm's."""

    if ctx.get("job"):
        return ctx["job"]
    said = _CITES.sub("", parse(answer).get("job", "")).split("|")[0].strip(" .\"“”").lower()
    if not said or _NONE.match(said):
        return None
    ids = {j["id"].lower(): j["id"] for j in ctx.get("jobs", [])}
    return ids.get(said) or next((ids[i] for i in ids if i in said), None)


def context(answer: str, text: str) -> dict:
    """The context layer's other findings: a conflict (verified only if its words are really in the input), what is
    still unknown, and one proposed next step for an agent."""

    lines, out = parse(answer), {"conflict": None, "unknown": None, "action": None}
    if (c := lines.get("conflict")) and not _NONE.match(_CITES.sub("", c.partition("|")[0])):
        what, _, rest = c.partition("|")
        m = _QUOTED.search(rest) or _QUOTED.search(c)
        phrase = locate(text, m.group(1)) if m else None
        what = _CITES.sub("", _QUOTED.sub("", what) if not rest else what).strip(" .;:")
        out["conflict"] = {"text": what, "phrase": phrase, "verified": bool(phrase)}
    if (u := lines.get("unknown")) and not _NONE.match(u):
        out["unknown"] = _CITES.sub("", u).strip(" .")
    if (a := lines.get("action")) and not _NONE.match(a):
        kind, sep, what = _CITES.sub("", a).partition(":")
        kind = kind.strip().lower().replace("follow up", "follow-up")
        if not sep or kind not in ACTIONS:
            kind, what = "follow-up", _CITES.sub("", a)
        what = what.strip(" .")
        if what and not _NONE.match(what):
            out["action"] = {"kind": kind, "text": what[:1].upper() + what[1:]}
    return out


def run(text: str, ctx: dict, ask=None) -> dict:
    """Reads one input. ``ask`` stands in for the reader in tests.

    An input the reader has already answered, with the same question and evidence, is answered again from the log at
    once (source "cache"; EXTRACT_CACHE=0 turns that off). The same input sent again while it is still being read waits
    for that answer."""

    q, passages, date = question(ctx), evidence(text, ctx), ctx["date"]
    text_sha = hashlib.sha256(text.strip().encode()).hexdigest()[:16]
    prompt_sha = hashlib.sha256(json.dumps([q, passages, date], ensure_ascii=False).encode()).hexdigest()[:16]
    result, source = None, "reader"
    if os.environ.get("EXTRACT_CACHE") != "0" and (result := reactor.cached(prompt_sha)):
        source = "cache"
    if result is None:
        result = reactor.shared(prompt_sha, lambda: (ask or llm.reader())(
            q, passages, date, meta={"note_sha": text_sha, "prompt_sha": prompt_sha}))
    if result.get("status") != "answered":
        raise NoAnswer(result)
    answer = "" if result.get("abstained") else result.get("answer", "")
    found, quotes, rejected = facts(answer, text)
    reply = parse(answer).get("reply")
    reply = re.sub(r"\s{2,}", " ", _CITES.sub("", reply)).strip() if reply and not _NONE.match(reply) else None
    return {
        "job": job(answer, ctx),
        "facts": found,
        "quotes": quotes,
        "rejected": rejected,
        **context(answer, text),
        "reply": reply,
        "reader": {"source": source, "reader": result.get("reader", "reactor"), "model": result.get("model"),
                   "latency_s": result.get("latency_s"), "call_id": result.get("call_id"),
                   "abstained": bool(result.get("abstained"))},
    }
