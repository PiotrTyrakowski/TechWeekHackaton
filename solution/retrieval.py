"""Retrieval over one dataset history: turn-level chunks, BM25 + dense hybrid scoring, session ranking."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from nltk.stem import PorterStemmer

STOP = set("""a an the and or but if then else of to in on at by for with from as is are was were be been being am do
does did doing have has had having i me my mine myself we our ours you your yours he him his she her hers it its they
them their what which who whom whose this that these those there here when where why how all any both each few more
most other some such no nor not only own same so than too very can will just should would could may might must shall
s t don't didn't about into over under again further once up down out off also really like get got just know think
want need please thanks thank yes ok okay hi hello sure much many""".split())

_stem = lru_cache(maxsize=None)(PorterStemmer().stem)
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
CHUNK_CHARS = 1200
CHUNK_STEP = 900


def tokens(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in STOP]


@dataclass
class Chunk:
    session: int  # index into history["sessions"]
    turn: int  # index into session["turns"]
    role: str
    text: str


def split_turn(content: str) -> list[str]:
    """A turn as one chunk, or overlapping windows when it is long (assistant answers often are)."""

    if len(content) <= CHUNK_CHARS:
        return [content]
    parts, start = [], 0
    while start < len(content):
        end = min(start + CHUNK_CHARS, len(content))
        if end < len(content):
            cut = content.rfind(" ", start + CHUNK_STEP // 2, end)
            end = cut if cut > 0 else end
        parts.append(content[start:end])
        if end >= len(content):
            break
        start = max(end - (CHUNK_CHARS - CHUNK_STEP), start + 1)
    return parts


def chunk_history(history: dict) -> list[Chunk]:
    out = []
    for si, session in enumerate(history["sessions"]):
        for ti, turn in enumerate(session["turns"]):
            for part in split_turn(turn["content"]):
                out.append(Chunk(si, ti, turn["role"], part))
    return out


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=float)
        self.avg = self.len.mean() if len(docs) else 1.0
        df = Counter(w for d in self.tf for w in d)
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.tf))
        norm = self.k1 * (1 - self.b + self.b * self.len / self.avg)
        for w in set(query):
            idf = self.idf.get(w)
            if idf is None:
                continue
            f = np.array([tf.get(w, 0) for tf in self.tf], dtype=float)
            out += idf * f * (self.k1 + 1) / (f + norm)
        return out


class Embedder:
    """Sentence embeddings with an on-disk cache keyed by model and text hash."""

    def __init__(self, model: str = "intfloat/multilingual-e5-base", cache: Path | None = None,
                 device: str | None = None) -> None:
        import sys

        sys.modules.setdefault("torchcodec", None)  # its broken FFmpeg binding raises on import; we need no audio
        from sentence_transformers import SentenceTransformer

        self.name = model
        self.model = SentenceTransformer(model, device=device)
        self.model.max_seq_length = 320
        if str(self.model.device).startswith("mps"):
            self.model.half()
        self.e5 = "e5" in model
        self.bge = "bge" in model
        self.cache = cache
        self.mem: dict[str, np.ndarray] = {}
        if cache:
            cache.mkdir(parents=True, exist_ok=True)

    def _key(self, text: str) -> str:
        return hashlib.sha1(f"{self.name}\0{text}".encode()).hexdigest()

    def passages(self, texts: list[str], session_ids: list[str] | None = None) -> np.ndarray:
        """Embeddings for passages; cached per session id when given (one .npy per session)."""

        prefix = "passage: " if self.e5 else ""
        return self._encode([prefix + t for t in texts])

    def query(self, text: str) -> np.ndarray:
        if self.e5:
            text = "query: " + text
        elif self.bge:
            text = "Represent this sentence for searching relevant passages: " + text
        return self._encode([text])[0]

    def _encode(self, texts: list[str]) -> np.ndarray:
        keys = [self._key(t) for t in texts]
        missing = [i for i, k in enumerate(keys) if k not in self.mem]
        if missing:
            vecs = self.model.encode([texts[i] for i in missing], batch_size=64, normalize_embeddings=True,
                                     show_progress_bar=False, convert_to_numpy=True)
            for i, v in zip(missing, vecs):
                self.mem[keys[i]] = v.astype(np.float32)
        return np.stack([self.mem[k] for k in keys])


class Reranker:
    """A cross-encoder that scores (question, passage) pairs; far better than BM25 or embeddings at telling which
    sentence actually answers the question."""

    def __init__(self, model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2", device: str | None = None) -> None:
        import sys

        sys.modules.setdefault("torchcodec", None)
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model, device=device, max_length=384)

    def score(self, query: str, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros(0)
        return np.asarray(self.model.predict([(query, t) for t in texts], batch_size=128, show_progress_bar=False),
                          dtype=float)


_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n+")


def split_sentences(text: str, short: int = 30, long: int = 400) -> list[str]:
    """Sentences, with fragments under ``short`` characters glued to their neighbour and long ones cut."""

    out: list[str] = []
    for piece in _SPLIT.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if out and (len(piece) < short or len(out[-1]) < short):
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    final = []
    for sent in out:
        while len(sent) > long:
            cut = sent.rfind(" ", 0, long)
            cut = cut if cut > long // 2 else long
            final.append(sent[:cut])
            sent = sent[cut:].lstrip()
        if sent:
            final.append(sent)
    return final


@dataclass
class Sentence:
    session: int
    turn: int
    index: int  # within the turn
    role: str
    text: str


def session_units(session: dict) -> tuple[list[str], list[str]]:
    """(chunk texts, sentence texts) of a session, in the order HistoryIndex lays them out."""

    chunks = [f"{t['role']}: {part}" for t in session["turns"] for part in split_turn(t["content"])]
    sents = [s for t in session["turns"] for s in split_sentences(t["content"])]
    return chunks, sents


class SessionCache:
    """Per-session chunk and sentence embeddings on disk: a session shared by several histories is embedded once."""

    def __init__(self, embedder: Embedder, root: Path) -> None:
        self.embedder = embedder
        self.root = root / embedder.name.replace("/", "__")
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, sid: str) -> tuple[Path, Path]:
        return self.root / f"{sid}.npy", self.root / f"{sid}.sent.npy"

    def prefetch(self, sessions: list[dict], batch: int = 20000) -> None:
        """Embeds every session not cached yet, many sessions per model call."""

        todo = [s for s in sessions if not all(p.exists() for p in self._paths(s["session_id"]))]
        seen = set()
        todo = [s for s in todo if not (s["session_id"] in seen or seen.add(s["session_id"]))]
        prefix = "passage: " if self.embedder.e5 else ""
        dim = self.embedder.model.get_sentence_embedding_dimension()
        for start in range(0, len(todo), 200):
            group = todo[start:start + 200]
            texts, spans = [], []
            for s in group:
                chunks, sents = session_units(s)
                a = len(texts)
                texts += [prefix + t for t in chunks]
                b = len(texts)
                texts += [prefix + t for t in sents]
                spans.append((a, b, len(texts)))
            order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
            vecs = np.zeros((len(texts), dim), np.float16)
            if texts:
                enc = self.embedder.model.encode([texts[i] for i in order], batch_size=128, normalize_embeddings=True,
                                                 show_progress_bar=False, convert_to_numpy=True)
                vecs[order] = enc.astype(np.float16)
            for s, (a, b, c) in zip(group, spans):
                pc, ps = self._paths(s["session_id"])
                np.save(pc, vecs[a:b])
                np.save(ps, vecs[b:c])

    def get(self, session: dict) -> tuple[np.ndarray, np.ndarray]:
        pc, ps = self._paths(session["session_id"])
        if not (pc.exists() and ps.exists()):
            self.prefetch([session])
        return np.load(pc), np.load(ps)


def zscore(x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return x
    sd = x.std()
    return (x - x.mean()) / (sd if sd > 1e-9 else 1.0)


class HistoryIndex:
    def __init__(self, history: dict, cache: SessionCache | None = None) -> None:
        self.history = history
        self.sessions = history["sessions"]
        self.chunks = chunk_history(history)
        self.sents = [Sentence(si, ti, k, t["role"], text)
                      for si, s in enumerate(self.sessions) for ti, t in enumerate(s["turns"])
                      for k, text in enumerate(split_sentences(t["content"]))]
        self.bm25 = BM25([tokens(c.text) for c in self.chunks])
        self.sent_bm25 = BM25([tokens(x.text) for x in self.sents])
        self.vecs = self.sent_vecs = None
        if cache is not None:
            cache.prefetch(self.sessions)
            got = [cache.get(s) for s in self.sessions]
            self.vecs = np.concatenate([g[0] for g in got]).astype(np.float32)
            self.sent_vecs = np.concatenate([g[1] for g in got]).astype(np.float32)
            assert len(self.vecs) == len(self.chunks), (len(self.vecs), len(self.chunks))
            assert len(self.sent_vecs) == len(self.sents), (len(self.sent_vecs), len(self.sents))
        self.chunk_session = np.array([c.session for c in self.chunks])

    def chunk_scores(self, question: str, qvec: np.ndarray | None = None, w_dense: float = 1.0,
                     w_bm25: float = 1.0) -> np.ndarray:
        score = np.zeros(len(self.chunks))
        if w_bm25:
            score += w_bm25 * zscore(self.bm25.scores(tokens(question)))
        if w_dense and qvec is not None and self.vecs is not None:
            score += w_dense * zscore(self.vecs @ qvec)
        return score

    def sentence_scores(self, question: str, qvec: np.ndarray | None = None, w_dense: float = 1.0,
                        w_bm25: float = 1.0) -> np.ndarray:
        score = np.zeros(len(self.sents))
        if w_bm25:
            score += w_bm25 * zscore(self.sent_bm25.scores(tokens(question)))
        if w_dense and qvec is not None and self.sent_vecs is not None:
            score += w_dense * zscore(self.sent_vecs @ qvec)
        return score

    def rerank(self, reranker: Reranker, query: str, first: np.ndarray, units: str, keep: int,
               user_all: bool = False, w_first: float = 0.3) -> np.ndarray:
        """Cross-encoder scores for the ``keep`` best units by ``first`` (plus every user sentence when ``user_all``),
        mixed with a little of ``first``; every other unit ranks below them."""

        items = self.sents if units == "sents" else self.chunks
        cand = set(np.argsort(-first)[:keep].tolist())
        if user_all:
            cand |= {i for i, x in enumerate(items) if x.role == "user"}
        cand = sorted(cand)
        ce = reranker.score(query, [f"{items[i].role}: {items[i].text}" for i in cand])
        out = np.full(len(items), -1e9)
        out[cand] = zscore(ce) + w_first * zscore(first[cand])
        return out

    def session_scores(self, chunk_scores: np.ndarray, top: int = 2, decay: float = 0.3) -> np.ndarray:
        """Each session's best chunk score plus a little of its next best ones."""

        out = np.full(len(self.sessions), -1e9)
        for si in range(len(self.sessions)):
            s = np.sort(chunk_scores[self.chunk_session == si])[::-1][:top]
            if len(s):
                out[si] = s[0] + decay * s[1:].sum()
        return out


def load_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_histories(path: Path, need: set[str]) -> dict[str, dict]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\{"history_id": "([^"]+)"', line)
            if m and m.group(1) in need:
                out[m.group(1)] = json.loads(line)
    return out
