"""Official Reactor client with explicit final-line citation instructions.

The outbound prompt changes and transport metadata is observed. Transport
behavior, final-answer extraction, abstention, and citation mapping remain the
organizer's code. No answer text is rewritten.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
import re
import sys
from unittest.mock import patch

from official.reactor import client as official

_build_message = official.build_message
_connect = official.websockets.connect if official.websockets else None


def _safe_metadata(value):
    text = str(value or "")
    key = os.environ.get("REACTOR_ACCESS_KEY", "")
    if key:
        text = text.replace(key, "[REDACTED]")
    return re.sub(r"rxk_[A-Za-z0-9_-]+", "[REDACTED]", text)[:500]


class ObservedSocket:
    """Transparent socket proxy; diagnostics exclude message bodies and headers."""

    def __init__(self, ws, diagnostics):
        self.ws = ws
        self.diagnostics = diagnostics
        self.sent_text = None

    def __getattr__(self, name):
        return getattr(self.ws, name)

    async def send(self, raw):
        try:
            self.sent_text = json.loads(raw).get("text")
        except (ValueError, TypeError, AttributeError):
            self.sent_text = None
        return await self.ws.send(raw)

    async def __aiter__(self):
        async for raw in self.ws:
            try:
                frame = json.loads(raw)
            except (ValueError, TypeError):
                frame = {}
            if isinstance(frame, dict):
                kind = frame.get("type")
                event = {"type": kind if kind in {"ack", "reply", "error", "ping", "pong"} else "other"}
                if isinstance(frame.get("cycle"), int):
                    event["cycle"] = frame["cycle"]
                if kind == "ack":
                    self.diagnostics["ack_observed"] = True
                    if self.sent_text is not None and frame.get("text") == self.sent_text:
                        self.diagnostics["ack_matches_sent_message"] = True
                if kind == "error":
                    event["code"] = _safe_metadata(frame.get("code"))
                if len(self.diagnostics["frames"]) < 64:
                    self.diagnostics["frames"].append(event)
            yield raw


@asynccontextmanager
async def diagnosed_connect(*args, **kwargs):
    ws = None
    diagnostics = {"event": "reactor_transport", "ack_observed": False,
                   "ack_matches_sent_message": False, "frames": []}
    try:
        async with _connect(*args, **kwargs) as ws:
            yield ObservedSocket(ws, diagnostics)
    finally:
        diagnostics["close_code"] = getattr(ws, "close_code", None)
        diagnostics["close_reason"] = _safe_metadata(getattr(ws, "close_reason", None))
        print(json.dumps(diagnostics), file=sys.stderr, flush=True)


def build_message(question: str, passages: list[dict], ref: str,
                  question_date: str | None = None) -> str:
    message = _build_message(question, passages, ref, question_date)
    instructions = [
        "Give one concise, direct answer. Do not list candidate answers or add an explanation before the final line.",
    ]
    if passages:
        labels = ", ".join(f"[E{i}]" for i in range(1, len(passages) + 1))
        instructions += [
            "The final answer line itself MUST include the evidence labels supporting your answer. "
            "A citation anywhere before the final answer line does not count.",
            f"Use only labels supplied in this question: {labels}. Never invent an evidence label or session ID.",
            f"Required form: # FINAL ANSWER [ref:{ref}]: <concise answer> [E1] "
            "(replace [E1] with the actual supporting label or labels).",
            f"If the evidence does not answer the question, output only: "
            f"# FINAL ANSWER [ref:{ref}]: {official.INSUFFICIENT}",
        ]
    return message + "\n\n" + "\n".join(instructions)


def main(argv=None):
    # Restore the imported module afterward, allowing callers/tests to use the
    # original official client without a persistent global modification.
    with patch.object(official, "build_message", build_message):
        if official.websockets:
            with patch.object(official.websockets, "connect", diagnosed_connect):
                return official.main(argv)
        return official.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
