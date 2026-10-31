"""HTTP for Fieldbook, standard library only. Serves the dashboard and the phone voice app too, so they share one origin
with the API:

    /                       the dashboard (frontend/dist)
    /voice/                 the phone voice app (voice/)

    GET  /health                 which reader (normal model or Reactor) and voice are ready, and why not
    GET  /state?since=V&wait=S   the inputs taken in so far; waits up to S seconds for a version newer than V
    POST /notes {text, date, jobs, passages?, job?, author_role?, channel?, clarifies?}
                                 an input (voice note, chat, SMS, note, document, correction): saved at once, read by
                                 the context layer in the background against the jobs and messages sent with it
    POST /actions/<id> {decision}        approved | dismissed: a person decides on the agent's proposed step
    POST /transcribe  audio body         -> {text}         ElevenLabs Scribe
    POST /speak   {text}                 -> audio/mpeg     ElevenLabs text-to-speech
    POST /reset                          forget the inputs taken in
    GET  /calls                          the last reader calls, as proof of what it answered

Errors: 503 when ElevenLabs isn't configured, 422 when it refused the audio, 400 for a malformed request. A reader
that isn't configured or gives no answer shows on the input itself (reading.status "failed", with the reason).

    python3 backend/server.py      # http://localhost:8787   (keys: backend/.env or the environment)
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import voice

voice.load_env()  # before the others read the environment

import llm  # noqa: E402
import reactor  # noqa: E402
import store  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SITES = {"/voice/": REPO / "voice", "/": REPO / "frontend" / "dist"}
MAX_BODY = 25 * 1024 * 1024

# Both web apps are served from here; other origins (a separate dev server) only when listed.
ORIGINS = set(filter(None, os.environ.get("ALLOW_ORIGINS", "").split(",")))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: object = None) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        if body is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self) -> None:
        self._send(204)

    def _json(self) -> dict | None:
        try:
            body = json.loads(self._body() or b"{}")
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(n)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/health":
            return self._send(200, {**llm.health(), "voice": {"ready": voice.ready() is None, "reason": voice.ready()}})
        if url.path == "/calls":
            return self._send(200, reactor.recent())
        if url.path == "/state":
            q = parse_qs(url.query)
            since = int(q["since"][0]) if q.get("since", [""])[0].isdigit() else None
            wait = min(float(q.get("wait", ["0"])[0] or 0), 25)
            return self._send(200, store.snapshot(since, wait))
        self._static(url.path)

    def _static(self, path: str) -> None:
        for prefix, root in SITES.items():
            if path == prefix.rstrip("/") and prefix != "/":
                self.send_response(301)
                self.send_header("Location", prefix)
                self.send_header("Content-Length", "0")
                return self.end_headers()
            if path.startswith(prefix):
                rel = path[len(prefix):] or "index.html"
                file = (root / rel).resolve()
                if file.is_dir():
                    file = file / "index.html"
                if root.resolve() in file.parents and file.is_file():
                    data = file.read_bytes()
                    self.send_response(200)
                    kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                    self.send_header("Content-Type", kind + ("; charset=utf-8" if kind.startswith("text/") or
                                                            kind.endswith("javascript") else ""))
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
                break
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/transcribe":
                return self._send(200, voice.transcribe(self._body(), self.headers.get("Content-Type") or ""))
            if path == "/speak":
                text = (self._json() or {}).get("text")
                if not isinstance(text, str) or not text.strip():
                    return self._send(400, {"error": "send JSON {\"text\": \"...\"}"})
                return self._send_bytes(200, voice.speak(text), "audio/mpeg")
            if path == "/reset":
                return self._send(200, store.reset())
            if path == "/notes":
                return self._note(self._json() or {})
            if m := re.fullmatch(r"/actions/([\w-]+)", path):
                done = store.decide(m.group(1), str((self._json() or {}).get("decision") or ""))
                return self._send(200, done) if done else self._send(409, {"error": "not a proposed action"})
            self._send(404, {"error": "not found"})
        except voice.Rejected as e:
            self._send(422, {"error": str(e)})
        except voice.Unavailable as e:
            self._send(503, {"error": str(e)})
        except ValueError as e:
            self._send(413, {"error": str(e)})

    def _note(self, body: dict) -> None:
        text, date, jobs = body.get("text"), str(body.get("date") or ""), body.get("jobs")
        if not isinstance(text, str) or not text.strip() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) \
                or not isinstance(jobs, list) or not all(isinstance(j, dict) and isinstance(j.get("id"), str) for j in jobs):
            return self._send(400, {"error": "send JSON {text, date: YYYY-MM-DD, jobs: [{id, ...}], passages?, job?}"})
        passages = [p for p in body.get("passages") or [] if isinstance(p, dict) and isinstance(p.get("text"), str)]
        self._send(201, store.add(text, date=date, jobs=jobs, passages=passages[-12:], job=body.get("job"),
                                  author_role=str(body.get("author_role") or "owner"),
                                  channel=str(body.get("channel") or "voice note"), clarifies=body.get("clarifies")))

    def _send_bytes(self, code: int, data: bytes, kind: str) -> None:
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def serve(port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8787))
    h = llm.health()
    print(f"dashboard http://localhost:{port}/   voice app http://localhost:{port}/voice/", file=sys.stderr)
    print(f"reader: {h['reader']} {h.get('model') or ''} ready={h['ready']} {h['reason'] or ''} | "
          f"voice ready={voice.ready() is None} {voice.ready() or ''}", file=sys.stderr)
    serve(port, os.environ.get("HOST", "127.0.0.1")).serve_forever()
