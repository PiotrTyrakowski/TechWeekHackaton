"""Our one door to Reactor: the kit's client.py, one question at a time, every call logged.

Nothing is sent unless REACTOR_LIVE=1, and never while a benchmark run (solution/run.py --split) is going: the team
shares one agent, and one --new-history resets the history everyone else is answering in. So we keep one history (on
disk, across restarts) and start another only when the agent dropped ours and nobody else is on it.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENT = Path(os.environ.get("REACTOR_CLIENT", ROOT.parent / "memory-challenge" / "reactor" / "client.py"))
LOG = Path(os.environ.get("REACTOR_LOG", ROOT / "logs" / "reactor_calls.jsonl"))
ENV = ("REACTOR_BASE_URL", "REACTOR_AGENT_ID", "REACTOR_ACCESS_KEY")

HISTORY = Path(os.environ.get("REACTOR_HISTORY_FILE", ROOT / "logs" / "reactor_history"))
LOCKFILE = ROOT / "logs" / "reactor.lock"
RUNS = ROOT.parent / "solution"  # the benchmark's output, to tell a run that is between two questions

_lock = threading.Lock()
_flights: dict[str, "_Flight"] = {}
_flights_lock = threading.Lock()


class Unavailable(Exception):
    """Reactor can't be asked right now; the app falls back to its own rules."""


class Busy(Exception):
    """Another note is being read; one question at a time per agent."""


def live() -> bool:
    return os.environ.get("REACTOR_LIVE") == "1"


def benchmark_running() -> bool:
    """A solution/run.py --split that asks Reactor, or another client.py talking to the agent. A --dry-run only builds
    messages and never touches the agent. Between two chained runs no process is up, so a run that wrote output in the
    last few minutes still counts."""

    ps = subprocess.run(["ps", "-Ao", "command="], capture_output=True, text=True).stdout
    for line in ps.splitlines():
        if "run.py --split" in line and "--dry-run" not in line:
            return True
    return _recent_run_output()


def _recent_run_output(minutes: float | None = None) -> bool:
    minutes = float(os.environ.get("REACTOR_QUIET_MINUTES", 10)) if minutes is None else minutes
    if minutes <= 0 or not RUNS.exists():
        return False
    since = time.time() - minutes * 60
    for path in [*RUNS.glob("runs/*/*"), *RUNS.glob("runs_*.log")]:
        try:
            if path.stat().st_mtime > since:
                return True
        except OSError:
            continue
    return False


def blocker() -> str | None:
    """Why Reactor would not be asked right now, or None."""

    if not live():
        return "REACTOR_LIVE is not 1"
    if missing := [k for k in ENV if not os.environ.get(k)]:
        return "not set: " + ", ".join(missing)
    if os.environ.get("REACTOR_SHARE_WITH_BENCHMARK") != "1" and benchmark_running():
        return "a benchmark run is using the agent"
    return None


def _client(*args: str, timeout: float) -> dict:
    cmd = [sys.executable, str(CLIENT), "--base-url", os.environ["REACTOR_BASE_URL"],
           "--agent-id", os.environ["REACTOR_AGENT_ID"], "--timeout", str(timeout), *args]
    try:
        # A margin over client.py's own timeout, so a stuck client can't hold the lock forever.
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f"client.py did not return within {timeout + 30:g} s"}
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        return {"status": "error", "error": (proc.stderr or proc.stdout).strip()[-500:]}
    if out.get("status") in ("closed", "error", "timeout") and proc.stderr.strip():
        out["stderr"] = proc.stderr.strip()[-500:]  # e.g. why the server closed the chat
    return out


def log(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}, ensure_ascii=False) + "\n")


def history() -> str | None:
    """The Reactor history our notes go to; kept on disk so a restarted server doesn't start (and wipe) another."""

    if env := os.environ.get("REACTOR_HISTORY"):
        return env
    try:
        return HISTORY.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _keep(history_id: str | None) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(history_id or "", encoding="utf-8")


def _start_history() -> dict:
    """--new-history wipes the agent for everyone using it, so only when nothing else is on it."""

    if os.environ.get("REACTOR_SHARE_WITH_BENCHMARK") != "1" and benchmark_running():
        raise Unavailable("a benchmark run is using the agent; not starting a history over it")
    new = _client("--new-history", timeout=120)
    log({"kind": "new-history", "response": new})
    if new.get("status") == "history":
        _keep(new["history_id"])
    return new


@contextlib.contextmanager
def _agent_lock():
    """One question at a time, across threads and across server processes on this machine."""

    if not _lock.acquire(blocking=False):
        raise Busy("Reactor is still reading the previous note")
    try:
        LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
        with LOCKFILE.open("a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise Busy("another backend process is asking Reactor") from None
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    finally:
        _lock.release()


def ask(question: str, passages: list[dict], question_date: str, *, meta: dict | None = None) -> dict:
    """client.py's JSON for one question, plus our ``call_id``.

    Keeps asking in the same history. A closed chat is asked once more in that history (the agent may just have been
    restarting); a new history is started only when there is none, or the agent's was replaced, and nothing else is
    using the agent -- a new history wipes whatever anyone else had in it."""

    if reason := blocker():
        raise Unavailable(reason)
    call_id = uuid.uuid4().hex[:12]
    with _agent_lock():
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(passages, f, ensure_ascii=False)
        try:
            timeout = float(os.environ.get("REACTOR_TIMEOUT", 240))
            result: dict = {}
            started = closed_retry = False
            for _ in range(3):
                current = history()
                if not current:
                    if started:
                        break
                    started = True
                    result = _start_history()
                    if result.get("status") != "history":
                        break
                    current = result["history_id"]
                result = _client("--history", current, "--question", question, "--question-date", question_date,
                                 "--evidence", f.name, timeout=timeout)
                if result.get("status") == "closed" and not closed_retry:
                    closed_retry = True
                    time.sleep(float(os.environ.get("REACTOR_CLOSED_WAIT", 5)))
                    continue
                if result.get("code") in ("history_changed", "history_required") and not started:
                    _keep(None)  # the next round starts one, if the agent is free
                    continue
                break
            result = {**result, "call_id": call_id}
            log({"kind": "extract", "call_id": call_id, "history_id": history(), "question_date": question_date,
                 "question": question, "passages": passages, "response": result, **(meta or {})})
            return result
        finally:
            Path(f.name).unlink(missing_ok=True)


class _Flight:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: dict | None = None
        self.error: BaseException | None = None


def shared(key: str, fn):
    """``fn()``, run once per key at a time: a second request for the same note waits for the answer already on its way
    instead of being turned away as busy."""

    with _flights_lock:
        flight = _flights.get(key)
        mine = flight is None
        if mine:
            flight = _flights[key] = _Flight()
    if not mine:
        flight.done.wait()
        if flight.error:
            raise flight.error
        return flight.result
    try:
        flight.result = fn()
        return flight.result
    except BaseException as e:
        flight.error = e
        raise
    finally:
        with _flights_lock:
            del _flights[key]
        flight.done.set()


def _entries() -> list[dict]:
    if not LOG.exists():
        return []
    return [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]


def _last_answer(field: str, value: str) -> dict | None:
    for e in reversed(_entries()):
        if e.get("kind") == "extract" and e.get(field) == value and e["response"].get("status") == "answered":
            return {**e["response"], "answered_at": e["at"]}
    return None


def cached(prompt_sha: str) -> dict | None:
    """Reactor's last answer to exactly this question and evidence, abstentions left out so they get asked again."""

    found = _last_answer("prompt_sha", prompt_sha)
    return found if found and not found.get("abstained") else None


def replay(note_sha: str) -> dict | None:
    """The last answered call for this exact note, even under an older question (EXTRACT_REPLAY=1, for rehearsals)."""

    return _last_answer("note_sha", note_sha)


def recent(n: int = 10) -> list[dict]:
    """The last calls, short enough to show as proof that Reactor answered."""

    return [{"at": e["at"], "call_id": e.get("call_id"), "status": e["response"].get("status"),
             "latency_s": e["response"].get("latency_s"), "answer": e["response"].get("answer"),
             "citations": e["response"].get("citations"), "history_id": e.get("history_id")}
            for e in _entries()[-n:] if e.get("kind") == "extract"]


def health() -> dict:
    reason = blocker()
    return {"ready": reason is None, "reason": reason, "busy": _lock.locked(), "live": live(),
            "configured": all(os.environ.get(k) for k in ENV), "client": CLIENT.exists(),
            "benchmark_running": benchmark_running(), "history_id": history(),
            "cache": os.environ.get("EXTRACT_CACHE") != "0", "replay": os.environ.get("EXTRACT_REPLAY") == "1"}
