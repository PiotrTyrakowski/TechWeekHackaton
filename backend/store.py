"""The inputs Fieldbook has taken in, shared by the dashboard and the phone voice app.

Each input (a voice note, a chat message, a short note, a document, a correction) is saved at once as a row in the
dashboard's SourceMessage shape with ``reading.status`` "reading", then read in the background by the context layer
(extract.py) against the jobs and earlier messages the sender passed along. When the reading is done the row carries
the job it is about and the verified facts; the dashboard's engine applies those instead of its own rules. The agent's
proposed next step waits on the row until a person approves or dismisses it.

Every change bumps ``version``, which the dashboard and the voice app long-poll. State lives in backend/logs/state.json;
POST /reset empties it.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid
from pathlib import Path

import extract
import reactor

ROOT = Path(__file__).resolve().parent
STATE = Path(os.environ.get("STATE_FILE", ROOT / "logs" / "state.json"))

CHANNELS = ["voice note", "chat", "sms", "note", "document", "correction"]
ROLES = ["owner", "customer", "worker"]

_lock = threading.RLock()
_changed = threading.Condition(_lock)
_state: dict | None = None


def _load() -> dict:
    global _state
    if _state is None:
        try:
            _state = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _state = {"version": 1, "rows": []}
        for r in _state["rows"]:  # a read cut short by a restart never finishes
            if r["reading"]["status"] == "reading":
                r["reading"] = {"status": "failed", "error": "the server restarted while reading"}
    return _state


def _save() -> None:
    _state["version"] += 1
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)
    _changed.notify_all()


def snapshot(since: int | None = None, wait: float = 0) -> dict:
    """All rows; with ``since``, waits up to ``wait`` seconds for a newer version first."""

    with _lock:
        _load()
        if since is not None and wait > 0:
            _changed.wait_for(lambda: _state["version"] != since, timeout=wait)
        return copy.deepcopy(_state)


def reset() -> dict:
    with _lock:
        _load()["rows"] = []
        _save()
        return copy.deepcopy(_state)


def _row(source_id: str) -> dict | None:
    return next((r for r in _load()["rows"] if r["source_id"] == source_id), None)


def _customer(jobs: list[dict], job: str | None) -> str | None:
    return next((j.get("customer") for j in jobs if j["id"] == job), None)


def add(text: str, *, date: str, jobs: list[dict], passages: list[dict] | None = None, job: str | None = None,
        author_role: str = "owner", channel: str = "voice note", clarifies: str | None = None,
        ask=None, background: bool = True) -> dict:
    """Saves the input and starts reading it. ``jobs`` and ``passages`` are the dashboard's jobs and the earlier
    messages the reader should see; ``job`` is set when the sender already picked one."""

    text = text.strip()
    job = job if job and any(j["id"] == job for j in jobs) else None
    ctx = {"date": date, "jobs": jobs, "passages": passages or [], "job": job,
           "author_role": author_role if author_role in ROLES else "owner",
           "channel": channel if channel in CHANNELS else "note"}
    row = {"source_id": "F_" + uuid.uuid4().hex[:10], "channel": ctx["channel"], "thread_id": "fieldbook",
           "contact_key": None, "conversation_title": _customer(jobs, job) or "New input", "job_context": job,
           "author_role": ctx["author_role"], "sent_at": f"{date}T{time.strftime('%H:%M:%S')}+01:00", "raw_text": text,
           "reading": {"status": "reading"}}
    if clarifies:
        row["clarifies_source_id"] = clarifies
    with _lock:
        _load()["rows"].append(row)
        _save()
    if background:
        threading.Thread(target=_read, args=(row["source_id"], ctx, ask), daemon=True).start()
    else:
        _read(row["source_id"], ctx, ask)
    return get(row["source_id"])


def get(source_id: str) -> dict | None:
    with _lock:
        r = _row(source_id)
        return copy.deepcopy(r) if r else None


def _read(source_id: str, ctx: dict, ask=None) -> None:
    text = get(source_id)["raw_text"]
    try:
        out = extract.run(text, ctx, ask=ask)
    except (reactor.Unavailable, reactor.Busy, extract.NoAnswer) as e:
        reading = {"status": "failed", "error": str(e)}
        out = None
    except Exception as e:  # never leave an input "reading" forever
        with _lock:
            _row(source_id)["reading"] = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
            _save()
        raise
    if out:
        action = out["action"] and {**out["action"], "status": "proposed"}
        reading = {"status": "done", "facts": out["facts"], "quotes": out["quotes"], "rejected": out["rejected"],
                   "conflict": out["conflict"], "unknown": out["unknown"], "action": action, "reply": out["reply"],
                   "reader": out["reader"], "context_size": len(ctx["passages"])}
    with _lock:
        row = _row(source_id)
        if out and out["job"]:
            row["job_context"] = out["job"]
            row["conversation_title"] = _customer(ctx["jobs"], out["job"]) or row["conversation_title"]
        row["reading"] = reading
        _save()


def decide(source_id: str, decision: str) -> dict | None:
    """A person approves or dismisses the agent's proposed step; nothing is done without it."""

    if decision not in ("approved", "dismissed"):
        return None
    with _lock:
        row = _row(source_id)
        action = row and row["reading"].get("action")
        if not action or action["status"] != "proposed":
            return None
        action.update(status=decision, decided_at=time.strftime("%Y-%m-%d %H:%M"))
        _save()
        return copy.deepcopy(row)
