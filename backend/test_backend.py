"""Offline checks: no Reactor calls. Run: python3 -m pytest backend -q"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import extract
import llm
import reactor
import server
import store
import voice

# A voice note from the owner about the Nowak bathroom, with the jobs as the dashboard sends them.
NOTE = "Nowak, Lipowa five: without the cabin it comes to four thousand three hundred. I'll call her tomorrow to confirm."
JOBS = [{"id": "lipowa 5", "address": "Lipowa 5", "customer": "Anna Nowak", "amount": 4800, "status": "pending",
         "excludes": []},
        {"id": "lesna 11", "address": "Leśna 11", "customer": "Ewa Wójcik", "amount": 1800, "status": "agreed",
         "excludes": [], "due": "2026-10-30"},
        {"id": "polna 9", "address": "Polna 9", "customer": "Łukasz Wiśniewski", "amount": 4100, "status": "pending",
         "excludes": []}]
PASSAGES = [{"id": "S01", "date": "2026-10-25",
             "text": "[chat, owner] lipowa5 bathroom labour 4.8k with the cabin. text me if anything"},
            {"id": "S05", "date": "2026-10-27",
             "text": "[chat, customer] hey actually do not install the cabin. my brother-in-law will handle it."}]
CTX = {"date": "2026-10-30", "jobs": JOBS, "passages": PASSAGES, "author_role": "owner", "channel": "voice note"}


@pytest.fixture(autouse=True)
def own_log(tmp_path, monkeypatch):
    """Each test gets an empty call log, so real answers in backend/logs never turn into cache hits here."""
    monkeypatch.setattr(reactor, "LOG", tmp_path / "calls.jsonl")
    monkeypatch.setattr(reactor, "HISTORY", tmp_path / "history")
    monkeypatch.setattr(reactor, "LOCKFILE", tmp_path / "reactor.lock")
    monkeypatch.setattr(reactor, "RUNS", tmp_path / "solution")
    monkeypatch.setenv("REACTOR_CLOSED_WAIT", "0")
    monkeypatch.delenv("REACTOR_HISTORY", raising=False)
    for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "READER",
              "LLM_MODEL", "ELEVENLABS_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(store, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(store, "_state", None)
    monkeypatch.setattr(voice, "CACHE", tmp_path / "speech")
    monkeypatch.setattr(voice, "_voice", None)

# What a good answer looks like (after the final-answer marker).
GOOD = """job: lipowa 5
amount: 4300 | "four thousand three hundred" [E3]
status: pending | "without the cabin it comes to four thousand three hundred" [E3]
due: 2026-10-31 | "I'll call her tomorrow" [E3]
start: UNCHANGED
excludes: shower cabin install | "without the cabin" [E3]
budget: UNCHANGED
conflict: the new price 4300 replaces the 4.8k quoted with the cabin | "four thousand three hundred" [E3] [E1]
unknown: whether Mrs Nowak accepts 4300
action: follow-up: call Anna Nowak to confirm 4300 without the cabin
reply: Hello Mrs Nowak, without the cabin the price is 4300 PLN. Can we confirm? [E1][E2][E3]"""


def answered(answer: str, **extra) -> dict:
    return {"status": "answered", "answer": answer, "latency_s": 7.2, "history_id": "h1", "call_id": "c1", **extra}


def test_the_question_lists_the_jobs_and_puts_the_input_last():
    passages = extract.evidence(NOTE, CTX)
    assert len(passages) == 3 and passages[-1]["id"] == "input" and passages[-1]["text"] == f"[voice note, owner] {NOTE}"
    q = extract.question(CTX)
    assert "[E3]" in q and "- lipowa 5 · Anna Nowak · 4800 PLN · awaiting the customer's decision" in q
    assert "job: <the id" in q and "Today is 2026-10-30" in q
    assert "job: <the id" not in extract.question({**CTX, "job": "lipowa 5"})  # the sender already picked it
    assert len(q) + sum(len(p["text"]) + 60 for p in passages) < 16000  # client.py's default limit


def test_good_answer_gives_verified_facts():
    out = extract.run(NOTE, CTX, ask=lambda *a, **k: answered(GOOD))
    assert out["job"] == "lipowa 5"
    assert out["facts"] == {"amount": 4300, "status": "pending", "due": "2026-10-31", "excludes": "shower cabin install"}
    for key, phrase in out["quotes"].items():  # the dashboard highlights by case-insensitive substring
        assert phrase.lower() in NOTE.lower(), key
    assert out["conflict"]["verified"] and out["unknown"] == "whether Mrs Nowak accepts 4300"
    assert out["action"] == {"kind": "follow-up", "text": "Call Anna Nowak to confirm 4300 without the cabin"}
    assert out["rejected"] == [] and out["reply"].startswith("Hello") and "[E" not in out["reply"]
    assert out["reader"]["source"] == "reader" and out["reader"]["latency_s"] == 7.2


def test_words_not_in_the_input_and_bad_values_are_rejected():
    answer = GOOD.replace("I'll call her tomorrow", "ring on Saturday").replace("status: pending", "status: exploded")
    out = extract.run(NOTE, CTX, ask=lambda *a, **k: answered(answer))
    assert "due" not in out["facts"] and "status" not in out["facts"]
    assert {r["key"] for r in out["rejected"]} == {"due", "status"}


def test_near_quotes_map_to_the_inputs_words():
    assert extract.locate(NOTE, "without cabin it comes to four thousand three hundred") == \
        "without the cabin it comes to four thousand three hundred"
    assert extract.locate(NOTE, "I’ll call her tomorrow") == "I'll call her tomorrow"
    assert extract.locate(NOTE, "boiler replaced") is None


def test_the_job_must_be_one_of_the_firms():
    assert extract.run(NOTE, CTX, ask=lambda *a, **k: answered("job: Lipowa 5 [E3]"))["job"] == "lipowa 5"
    assert extract.run(NOTE, CTX, ask=lambda *a, **k: answered("job: brzozowa 99"))["job"] is None
    assert extract.run(NOTE, CTX, ask=lambda *a, **k: answered("job: NONE"))["job"] is None
    assert extract.run(NOTE, {**CTX, "job": "polna 9"}, ask=lambda *a, **k: answered(GOOD))["job"] == "polna 9"


def test_loose_formatting_and_unchanged():
    answer = """Here you go.
- **amount**: 4,300 "four thousand three hundred" [E3]
status: unchanged [E2]
due: —
excludes: no change
conflict: none
action: NONE"""
    out = extract.run(NOTE, CTX, ask=lambda *a, **k: answered(answer))
    assert out["facts"] == {"amount": 4300} and out["reply"] is None
    assert out["conflict"] is None and out["action"] is None and out["job"] is None


def test_abstained_means_no_facts():
    out = extract.run(NOTE, CTX, ask=lambda *a, **k: answered("INSUFFICIENT_EVIDENCE", abstained=True))
    assert out["facts"] == {} and out["reader"]["abstained"]


def test_no_answer_raises():
    with pytest.raises(extract.NoAnswer):
        extract.run(NOTE, CTX, ask=lambda *a, **k: {"status": "timeout"})

def test_off_unless_live(monkeypatch):
    monkeypatch.delenv("REACTOR_LIVE", raising=False)
    with pytest.raises(reactor.Unavailable):
        reactor.ask("q", [], "2026-10-29")


def test_refuses_while_the_benchmark_runs(monkeypatch):
    monkeypatch.setenv("REACTOR_LIVE", "1")
    for k in reactor.ENV:
        monkeypatch.setenv(k, "x")
    monkeypatch.setattr(reactor, "benchmark_running", lambda: True)
    monkeypatch.setattr(reactor, "_client", lambda *a, **k: pytest.fail("agent called"))
    with pytest.raises(reactor.Unavailable, match="benchmark"):
        reactor.ask("q", [], "2026-10-29")


@pytest.fixture
def http(monkeypatch):
    srv = server.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(url, method="POST", body=None, origin="http://localhost:5173"):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Origin": origin})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_http_cors_only_for_listed_origins(http, monkeypatch):
    status, headers, _ = call(http + "/notes", method="OPTIONS")
    assert status == 204 and "Access-Control-Allow-Origin" not in headers
    monkeypatch.setattr(server, "ORIGINS", {"http://localhost:5173"})
    status, headers, _ = call(http + "/notes", method="OPTIONS")
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


def test_http_errors_and_health(http, monkeypatch):
    assert call(http + "/notes", body={"text": NOTE})[0] == 400  # no date or jobs
    assert call(http + "/notes", body={"text": "  ", "date": "2026-10-30", "jobs": JOBS})[0] == 400
    assert call(http + "/transcribe", body={})[0] == 422  # JSON is not audio
    assert call(http + "/actions/F_nope", body={"decision": "approved"})[0] == 409
    status, _, body = call(http + "/health", method="GET")
    health = json.loads(body)
    assert status == 200 and health["reader"] == "llm" and health["ready"] is False
    assert health["reactor"]["reason"] == "REACTOR_LIVE is not 1" and health["voice"]["ready"] is False
    monkeypatch.setenv("READER", "reactor")
    assert json.loads(call(http + "/health", method="GET")[2])["reason"] == "REACTOR_LIVE is not 1"


def logging_ask(answer: dict, calls: list):
    """Stands in for the reader: counts the call and logs it the way the real one does."""
    def ask(question, passages, question_date, *, meta=None):
        calls.append(question)
        reactor.log({"kind": "extract", "call_id": answer.get("call_id"), "response": answer, **(meta or {})})
        return answer
    return ask


def test_an_input_already_answered_comes_back_at_once(monkeypatch):
    calls = []
    first = extract.run(NOTE, CTX, ask=logging_ask(answered(GOOD), calls))
    again = extract.run(NOTE, CTX, ask=lambda *a, **k: pytest.fail("asked twice for the same input"))
    assert first["reader"]["source"] == "reader" and again["reader"]["source"] == "cache"
    assert again["facts"] == first["facts"] and again["reply"] == first["reply"]
    monkeypatch.setenv("EXTRACT_CACHE", "0")
    assert extract.run(NOTE, CTX, ask=logging_ask(answered(GOOD), calls))["reader"]["source"] == "reader"
    assert len(calls) == 2


def test_a_different_input_or_an_abstention_is_asked_again():
    calls = []
    extract.run(NOTE, CTX, ask=logging_ask(answered("INSUFFICIENT_EVIDENCE", abstained=True), calls))
    extract.run(NOTE, CTX, ask=logging_ask(answered(GOOD), calls))
    extract.run(NOTE + " Thanks.", CTX, ask=logging_ask(answered(GOOD), calls))
    assert len(calls) == 3


def test_the_same_input_twice_at_once_asks_once():
    calls, results = [], []

    def slow(*a, **k):
        calls.append(1)
        threading.Event().wait(0.3)
        return answered(GOOD)

    threads = [threading.Thread(target=lambda: results.append(extract.run(NOTE, CTX, ask=slow))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and [len(r["facts"]) for r in results] == [4, 4]

def test_a_stuck_client_times_out(monkeypatch):
    for k in reactor.ENV:
        monkeypatch.setenv(k, "x")

    def stuck(cmd, **kw):
        raise reactor.subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(reactor.subprocess, "run", stuck)
    assert reactor._client("--new-history", timeout=1)["status"] == "timeout"


def test_a_dry_run_does_not_hold_the_agent(monkeypatch):
    def ps(lines):
        out = type("P", (), {"stdout": "\n".join(lines)})()
        monkeypatch.setattr(reactor.subprocess, "run", lambda *a, **k: out)

    ps(["python3 run.py --split ../memory-challenge/test --out runs/t2 --dry-run", "python3 backend/server.py"])
    assert not reactor.benchmark_running()
    ps(["python3 run.py --split ../memory-challenge/test --out runs/test --reuse"])
    assert reactor.benchmark_running()


@pytest.fixture
def agent(monkeypatch):
    """A scripted agent: each _client call takes the next canned reply; the calls are kept to check."""
    monkeypatch.setenv("REACTOR_LIVE", "1")
    for k in reactor.ENV:
        monkeypatch.setenv(k, "x")
    monkeypatch.setattr(reactor, "benchmark_running", lambda: False)
    state = {"replies": [], "calls": []}

    def client(*args, timeout):
        state["calls"].append(args[0] if args[0] == "--new-history" else ("ask", args[1]))
        return state["replies"].pop(0)

    monkeypatch.setattr(reactor, "_client", client)
    return state


def test_history_is_kept_across_restarts(agent):
    agent["replies"] = [{"status": "history", "history_id": "h1"}, answered(GOOD), answered(GOOD)]
    reactor.ask("q", [], "2026-10-29")
    reactor.ask("q", [], "2026-10-29")
    assert agent["calls"] == ["--new-history", ("ask", "h1"), ("ask", "h1")]
    assert reactor.HISTORY.read_text() == "h1"


def test_a_closed_chat_is_asked_again_in_the_same_history(agent):
    reactor._keep("h1")
    agent["replies"] = [{"status": "closed"}, answered(GOOD)]
    assert reactor.ask("q", [], "2026-10-29")["status"] == "answered"
    assert agent["calls"] == [("ask", "h1"), ("ask", "h1")]  # never a --new-history: that wipes the agent


def test_closed_twice_gives_up_without_a_new_history(agent):
    reactor._keep("h1")
    agent["replies"] = [{"status": "closed"}, {"status": "closed"}]
    assert reactor.ask("q", [], "2026-10-29")["status"] == "closed"
    assert "--new-history" not in agent["calls"]


def test_a_replaced_history_starts_ours_only_when_the_agent_is_free(agent, monkeypatch):
    reactor._keep("h1")
    agent["replies"] = [{"status": "refused", "code": "history_changed", "current_history_id": "teammate"},
                        {"status": "history", "history_id": "h2"}, answered(GOOD)]
    assert reactor.ask("q", [], "2026-10-29")["status"] == "answered"
    assert agent["calls"] == [("ask", "h1"), "--new-history", ("ask", "h2")]

    agent["calls"].clear()
    agent["replies"] = [{"status": "refused", "code": "history_changed", "current_history_id": "benchmark"}]
    calls = iter([False, True])  # free when asked, then a benchmark run starts
    monkeypatch.setattr(reactor, "benchmark_running", lambda: next(calls))
    with pytest.raises(reactor.Unavailable, match="benchmark"):
        reactor.ask("q", [], "2026-10-29")
    assert agent["calls"] == [("ask", "h2")]


def test_a_run_between_two_questions_still_holds_the_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(reactor.subprocess, "run", lambda *a, **k: type("P", (), {"stdout": ""})())
    out = reactor.RUNS / "runs" / "test2"
    out.mkdir(parents=True)
    (out / "predictions.jsonl").write_text("{}")
    assert reactor.benchmark_running()
    monkeypatch.setenv("REACTOR_QUIET_MINUTES", "0")
    assert not reactor.benchmark_running()


def test_one_question_at_a_time_across_processes(agent):
    import fcntl
    reactor.LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    with reactor.LOCKFILE.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # another server process holding the agent
        with pytest.raises(reactor.Busy):
            reactor.ask("q", [], "2026-10-29")
    assert agent["calls"] == []


# --- the normal model, the shared store, ElevenLabs ------------------------------------------------------------------

def test_the_normal_model_answers_like_reactor(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    sent = []
    monkeypatch.setattr(llm, "complete", lambda text, timeout=90: sent.append(text) or "Thinking...\n# FINAL ANSWER:\n" + GOOD)
    out = extract.run(NOTE, CTX)  # READER defaults to the normal model
    assert out["facts"]["amount"] == 4300 and out["reader"]["reader"] == "llm"
    assert "[E3]" in sent[0] and NOTE in sent[0] and "Anna Nowak" in sent[0]
    assert reactor.recent()[-1]["status"] == "answered"


def test_the_normal_model_without_a_key_is_unavailable():
    with pytest.raises(reactor.Unavailable, match="OPENROUTER_API_KEY"):
        extract.run(NOTE, CTX)


def add(text=NOTE, ask=None, **kw):
    return store.add(text, date="2026-10-30", jobs=JOBS, passages=PASSAGES, ask=ask or (lambda *a, **k: answered(GOOD)),
                     background=False, **kw)


def test_an_input_becomes_a_row_the_dashboard_can_apply():
    v0 = store.snapshot()["version"]
    row = add()
    assert row["source_id"].startswith("F_") and row["raw_text"] == NOTE and row["channel"] == "voice note"
    assert row["sent_at"].startswith("2026-10-30T") and row["author_role"] == "owner"
    assert row["job_context"] == "lipowa 5" and row["conversation_title"] == "Anna Nowak"
    r = row["reading"]
    assert r["status"] == "done" and r["facts"]["amount"] == 4300 and r["quotes"]["due"] == "I'll call her tomorrow"
    assert r["action"]["status"] == "proposed" and r["reader"]["reader"] == "reactor" and r["context_size"] == 2
    st = store.snapshot()
    assert st["rows"] == [row] and st["version"] > v0 and store.STATE.exists()


def test_the_sender_can_pick_the_job_and_the_channel():
    row = add("ok we confirm", ask=lambda *a, **k: answered('status: agreed | "we confirm" [E3]'),
              job="polna 9", author_role="customer", channel="chat")
    assert row["job_context"] == "polna 9" and row["conversation_title"] == "Łukasz Wiśniewski"
    assert row["channel"] == "chat" and row["author_role"] == "customer" and row["reading"]["facts"] == {"status": "agreed"}
    assert add("x", channel="carrier pigeon", job="nope")["channel"] == "note"


def test_an_input_without_a_job_stays_unplaced():
    row = add("the place on the corner, call back", ask=lambda *a, **k: answered("job: NONE\nunknown: which customer"))
    assert row["job_context"] is None and row["reading"]["status"] == "done" and row["reading"]["unknown"] == "which customer"
    assert add("that was Lesna 11", clarifies=row["source_id"])["clarifies_source_id"] == row["source_id"]


def test_a_failed_read_is_kept_with_its_reason():
    row = store.add(NOTE, date="2026-10-30", jobs=JOBS, background=False)  # no model key
    assert row["reading"]["status"] == "failed" and "OPENROUTER_API_KEY" in row["reading"]["error"]
    assert row["job_context"] is None


def test_a_person_decides_on_the_agents_step():
    row = add()
    assert store.decide(row["source_id"], "maybe") is None
    assert store.decide(row["source_id"], "approved")["reading"]["action"]["status"] == "approved"
    assert store.decide(row["source_id"], "dismissed") is None  # already decided


def test_a_restart_mid_read_does_not_leave_it_reading(monkeypatch):
    store.STATE.write_text(json.dumps({"version": 3, "rows": [{"source_id": "F_1", "reading": {"status": "reading"}}]}))
    monkeypatch.setattr(store, "_state", None)
    assert store.snapshot()["rows"][0]["reading"]["status"] == "failed"


def test_reset_forgets_the_inputs():
    add()
    assert store.reset()["rows"] == []


def test_http_notes_state_and_both_sites(http, monkeypatch):
    monkeypatch.setattr(llm, "reader", lambda: (lambda *a, **k: answered(GOOD)))
    status, _, body = call(http + "/notes", body={"text": NOTE, "date": "2026-10-30", "jobs": JOBS, "passages": PASSAGES})
    row = json.loads(body)
    assert status == 201 and row["reading"]["status"] in ("reading", "done")
    for _ in range(50):
        st = json.loads(call(http + "/state", method="GET")[2])
        if st["rows"][-1]["reading"]["status"] == "done":
            break
        threading.Event().wait(0.05)
    assert st["rows"][-1]["job_context"] == "lipowa 5"
    status, _, body = call(http + f"/actions/{row['source_id']}", body={"decision": "approved"})
    assert status == 200 and json.loads(body)["reading"]["action"]["status"] == "approved"
    v = json.loads(call(http + "/state", method="GET")[2])["version"]
    started = time.monotonic()
    assert json.loads(call(http + f"/state?since={v}&wait=0.3", method="GET")[2])["version"] == v
    assert time.monotonic() - started >= 0.25  # waited for news that never came
    for path in ("/", "/voice/"):
        status, headers, page = call(http + path, method="GET")
        assert status == 200 and b"Fieldbook" in page and headers["Content-Type"].startswith("text/html")
    assert call(http + "/engine.js", method="GET")[1]["Content-Type"].startswith("text/javascript")
    assert call(http + "/../backend/.env", method="GET")[0] == 404

@pytest.fixture
def eleven(monkeypatch):
    """A fake ElevenLabs on localhost: records each request, answers like the real API."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []

    class Fake(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(("GET", self.path, {k.lower(): v for k, v in self.headers.items()}, b""))
            self._reply(200, json.dumps({"voices": [{"voice_id": "premade1", "name": "Adam"}]}).encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(("POST", self.path, {k.lower(): v for k, v in self.headers.items()}, body))
            if self.path.startswith("/v1/speech-to-text"):
                if b"tooshort" in body:
                    return self._reply(422, json.dumps({"detail": [{"loc": ["file"], "msg": "Audio too short",
                                                                     "type": "value_error"}]}).encode())
                return self._reply(200, json.dumps({"text": " " + NOTE + " ", "language_code": "eng",
                                                    "audio_duration_secs": 9.4}).encode())
            self._reply(200, b"ID3fake-mp3", "audio/mpeg")

        def _reply(self, code, data, kind="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("ELEVENLABS_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    yield seen
    srv.shutdown()


def test_transcribe_sends_the_audio_to_scribe(eleven, http):
    req = urllib.request.Request(http + "/transcribe", data=b"\x1aE\xdf\xa3webm-bytes", method="POST",
                                 headers={"Content-Type": "audio/webm;codecs=opus"})
    with urllib.request.urlopen(req) as r:
        out = json.loads(r.read())
    assert out["text"] == NOTE and out["language_code"] == "eng"
    method, path, headers, body = eleven[0]
    assert path == "/v1/speech-to-text" and headers["xi-api-key"] == "test-key"
    assert b'name="model_id"\r\n\r\nscribe_v2' in body and b'filename="note.webm"' in body
    assert b"webm-bytes" in body and b"language_code" not in body  # detected, not pinned


def test_transcribe_errors(eleven):
    with pytest.raises(voice.Rejected, match="too short"):
        voice.transcribe(b"tooshort", "audio/webm")
    with pytest.raises(voice.Rejected):
        voice.transcribe(b"", "audio/webm")
    with pytest.raises(voice.Rejected):
        voice.transcribe(b"x", "text/plain")


def test_speak_picks_a_voice_and_caches(eleven, http):
    status, headers, audio = call(http + "/speak", body={"text": "Your Golf is ready tomorrow."})
    assert status == 200 and headers["Content-Type"] == "audio/mpeg" and audio == b"ID3fake-mp3"
    assert call(http + "/speak", body={"text": "Your Golf is ready tomorrow."})[2] == audio
    paths = [p for _, p, _, _ in eleven]
    assert paths == ["/v2/voices?category=premade&page_size=100",
                     "/v1/text-to-speech/premade1?output_format=mp3_44100_128"]  # second time from disk
    assert json.loads(eleven[1][3])["model_id"] == "eleven_multilingual_v2"


def test_voice_needs_a_key_and_https(monkeypatch):
    with pytest.raises(voice.Unavailable, match="ELEVENLABS_API_KEY"):
        voice.transcribe(b"abc", "audio/webm")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_BASE_URL", "http://evil.example")
    with pytest.raises(voice.Unavailable, match="https"):
        voice.speak("hi")


def test_env_file_does_not_override_the_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# keys\nELEVENLABS_API_KEY='from-file'\nLLM_MODEL=from-file\n")
    monkeypatch.setenv("LLM_MODEL", "from-env")
    voice.load_env(env)
    assert os.environ["ELEVENLABS_API_KEY"] == "from-file" and os.environ["LLM_MODEL"] == "from-env"
