"""ElevenLabs, server side only: the key never reaches a browser.

    transcribe(audio, content_type) -> {text, language_code, duration_s}   Scribe speech-to-text
    speak(text)                     -> mp3 bytes                           text-to-speech, cached on disk

The key is ELEVENLABS_API_KEY, from the environment or backend/.env (gitignored). ELEVENLABS_BASE_URL may point at a
local fake for tests; anything but https is refused unless it is localhost.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "logs" / "speech"
STT_MODEL = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2")
TTS_MODEL = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/x-m4a", "audio/mpeg", "audio/wav", "audio/x-wav",
               "audio/aac", "video/webm", "video/mp4"}
MAX_AUDIO = 25 * 1024 * 1024


class Unavailable(Exception):
    """No key, or ElevenLabs could not be reached; the caller says so instead of guessing."""


class Rejected(Exception):
    """ElevenLabs refused this input (too short, wrong format, ...)."""


def load_env(path: Path = ROOT / ".env") -> None:
    """KEY=value lines from backend/.env, without overriding what the environment already has."""

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _base() -> str:
    base = os.environ.get("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").rstrip("/")
    url = urlparse(base)
    if url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1"):
        raise Unavailable("ELEVENLABS_BASE_URL must be https")
    return base


def ready() -> str | None:
    """Why voice would not work right now, or None."""

    return None if os.environ.get("ELEVENLABS_API_KEY") else "ELEVENLABS_API_KEY is not set"


def _call(path: str, data: bytes, content_type: str, *, accept: str = "application/json", timeout: float = 60) -> bytes:
    if reason := ready():
        raise Unavailable(reason)
    req = urllib.request.Request(_base() + path, data=data, method="POST", headers={
        "xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": content_type, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        if e.code in (400, 422):
            raise Rejected(_message(detail) or f"HTTP {e.code}") from None
        raise Unavailable(f"ElevenLabs HTTP {e.code}: {_message(detail) or e.reason}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise Unavailable(f"ElevenLabs unreachable: {getattr(e, 'reason', e)}") from None


def _message(body: str) -> str | None:
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        return body.strip() or None
    if isinstance(detail, list):  # 422: [{loc, msg, type}]
        return "; ".join(d.get("msg", "") for d in detail if isinstance(d, dict)) or None
    if isinstance(detail, dict):
        return detail.get("message") or detail.get("status")
    return str(detail) if detail else None


def transcribe(audio: bytes, content_type: str = "audio/webm") -> dict:
    """Scribe on one recorded note. The language is detected unless ELEVENLABS_LANGUAGE pins it (e.g. pol)."""

    kind = content_type.split(";")[0].strip().lower() or "audio/webm"
    if kind not in AUDIO_TYPES:
        raise Rejected(f"not an audio type: {kind}")
    if not audio:
        raise Rejected("empty recording")
    if len(audio) > MAX_AUDIO:
        raise Rejected("recording too long")
    ext = {"audio/mp4": "m4a", "audio/x-m4a": "m4a", "video/mp4": "m4a", "audio/mpeg": "mp3", "audio/ogg": "ogg",
           "audio/wav": "wav", "audio/x-wav": "wav", "audio/aac": "aac"}.get(kind, "webm")
    fields = {"model_id": STT_MODEL, "tag_audio_events": "false"}
    if lang := os.environ.get("ELEVENLABS_LANGUAGE"):
        fields["language_code"] = lang
    boundary = uuid.uuid4().hex
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items())
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="note.{ext}"\r\n'
             f"Content-Type: {kind}\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    out = json.loads(_call("/v1/speech-to-text", body, f"multipart/form-data; boundary={boundary}"))
    return {"text": (out.get("text") or "").strip(), "language_code": out.get("language_code"),
            "duration_s": out.get("audio_duration_secs"), "transcription_id": out.get("transcription_id")}


def voice_id() -> str:
    """ELEVENLABS_VOICE_ID, else the first premade voice the account can use (looked up once)."""

    global _voice
    if v := os.environ.get("ELEVENLABS_VOICE_ID"):
        return v
    if _voice:
        return _voice
    if reason := ready():
        raise Unavailable(reason)
    req = urllib.request.Request(_base() + "/v2/voices?category=premade&page_size=100",
                                 headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            voices = json.loads(r.read()).get("voices") or []
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise Unavailable(f"could not list ElevenLabs voices: {e}") from None
    if not voices:
        raise Unavailable("no ElevenLabs voice available; set ELEVENLABS_VOICE_ID")
    _voice = voices[0]["voice_id"]
    return _voice


_voice: str | None = None


def speak(text: str) -> bytes:
    """MP3 of ``text``. The same text in the same voice is read from disk, not paid for again."""

    text = text.strip()
    if not text:
        raise Rejected("nothing to say")
    if len(text) > 1500:
        raise Rejected("text too long to read out")
    vid = voice_id()
    key = hashlib.sha256(f"{vid}|{TTS_MODEL}|{text}".encode()).hexdigest()[:24]
    path = CACHE / f"{key}.mp3"
    if path.exists():
        return path.read_bytes()
    body = json.dumps({"text": text, "model_id": TTS_MODEL,
                       "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}).encode()
    audio = _call(f"/v1/text-to-speech/{vid}?output_format=mp3_44100_128", body, "application/json",
                  accept="audio/mpeg")
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return audio
