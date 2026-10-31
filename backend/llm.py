"""A normal hosted model in Reactor's place, answering in the same shape, so everything after the answer is the same.

    READER=llm (default)     this module: OpenRouter (OPENROUTER_API_KEY) or Anthropic (ANTHROPIC_API_KEY)
    READER=reactor           reactor.py, the team's Reactor agent

The message is the one Reactor gets: the question, the date, the passages as [E1]..[En], and a request to end with a
final-answer line. LLM_MODEL picks the model.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid

import reactor

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
ANTHROPIC = os.environ.get("ANTHROPIC_API_URL", "https://api.anthropic.com") + "/v1/messages"
_FINAL = re.compile(r"#\s*FINAL ANSWER[^:\n]*:\s*", re.I)


def provider() -> str | None:
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def model() -> str:
    return os.environ.get("LLM_MODEL") or {"openrouter": "deepseek/deepseek-v4.1-flash-1017",
                                           "anthropic": "claude-sonnet-5-5"}.get(provider() or "", "")


def blocker() -> str | None:
    return None if provider() else "set OPENROUTER_API_KEY or ANTHROPIC_API_KEY"


def message(question: str, passages: list[dict], question_date: str) -> str:
    lines = [question, "", f"Today is {question_date}.", "", "Evidence:"]
    for i, p in enumerate(passages, 1):
        lines.append(f"[E{i}] {p['text']}")
    lines += ["", "Cite the passages you use as [E1], [E2], ... Finish with one line that starts with",
              "# FINAL ANSWER: and put the requested lines after it, nothing else after them."]
    return "\n".join(lines)


def _post(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def complete(text: str, timeout: float = 90) -> str:
    if provider() == "openrouter":
        out = _post(OPENROUTER, {"model": model(), "messages": [{"role": "user", "content": text}], "temperature": 0},
                    {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}, timeout)
        return out["choices"][0]["message"]["content"] or ""
    out = _post(ANTHROPIC, {"model": model(), "max_tokens": 1200, "messages": [{"role": "user", "content": text}]},
                {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}, timeout)
    return "".join(b.get("text", "") for b in out.get("content", []))


def ask(question: str, passages: list[dict], question_date: str, *, meta: dict | None = None) -> dict:
    """Same result shape as reactor.ask: status answered with the text after the final-answer marker."""

    if reason := blocker():
        raise reactor.Unavailable(reason)
    call_id, started = uuid.uuid4().hex[:12], time.monotonic()
    try:
        reply = complete(message(question, passages, question_date))
        parts = _FINAL.split(reply, maxsplit=1)
        answer = parts[1].strip() if len(parts) == 2 else reply.strip()
        result = {"status": "answered", "answer": answer, "reply": reply,
                  "abstained": answer.upper().startswith("INSUFFICIENT_EVIDENCE")}
    except urllib.error.HTTPError as e:
        result = {"status": "error", "error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"}
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as e:
        result = {"status": "error", "error": str(e)[:300]}
    result.update(call_id=call_id, latency_s=round(time.monotonic() - started, 1), model=model(), reader="llm")
    reactor.log({"kind": "extract", "call_id": call_id, "reader": "llm", "model": model(),
                 "question_date": question_date, "question": question, "passages": passages, "response": result,
                 **(meta or {})})
    return result


def reader():
    """The ask function for READER: this module unless READER=reactor."""

    return reactor.ask if os.environ.get("READER", "llm") == "reactor" else ask


def health() -> dict:
    name = os.environ.get("READER", "llm")
    if name == "reactor":
        h = reactor.health()
        return {"reader": "reactor", "ready": h["ready"], "reason": h["reason"], "reactor": h}
    return {"reader": "llm", "ready": blocker() is None, "reason": blocker(), "provider": provider(),
            "model": model(), "reactor": reactor.health()}
