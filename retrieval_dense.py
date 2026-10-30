"""Optional, offline MiniLM cosine retrieval and BM25/dense reciprocal-rank fusion.

Weights are never downloaded by retrieval. Set DENSE_MODEL_DIR to a directory
containing model_quantized.onnx and tokenizer.json. No gold is read here.
DENSE_CANDIDATE_LIMIT defaults to 16 (BM25 shortlist); 0 encodes all turns.
"""
from __future__ import annotations

import hashlib
import os
from collections import Counter, OrderedDict
from pathlib import Path

from retrieval import _rank, _excerpt

METHODS = ("dense", "dense-hybrid")
MODEL_ID = "Xenova/all-MiniLM-L6-v2"
MODEL_REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
_ENCODER = None


class Encoder:
    def __init__(self):
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise ValueError('Dense retrieval needs the optional requirements-dense.txt dependencies; use the documented Python 3.12 environment') from exc
        self.np = np
        directory = Path(os.environ.get("DENSE_MODEL_DIR", "experiments/dense-model"))
        if not all((directory / name).is_file() for name in ('model_quantized.onnx', 'tokenizer.json')):
            raise ValueError('Dense model assets missing: run experiments/dense-fetch-model.py or set DENSE_MODEL_DIR')
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.environ.get("DENSE_THREADS", "2"))
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.model = ort.InferenceSession(str(directory / "model_quantized.onnx"), options,
                                          providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding()
        self.cache = OrderedDict()
        # Content, rather than dates or question IDs, is the cache identity.
        self.cache_limit = 50000

    def encode(self, texts):
        np = self.np
        keys = [hashlib.sha256(t.encode()).digest() for t in texts]
        missing = dict((key, text) for key, text in zip(keys, texts) if key not in self.cache)
        items = list(missing.items())
        for start in range(0, len(items), 16):
            batch = items[start:start + 16]
            encoded = self.tokenizer.encode_batch([text for _, text in batch])
            inputs = {name: np.asarray([getattr(row, attr) for row in encoded], dtype=np.int64)
                      for name, attr in (("input_ids", "ids"), ("attention_mask", "attention_mask"),
                                         ("token_type_ids", "type_ids"))}
            tokens = self.model.run(None, inputs)[0]
            mask = inputs["attention_mask"][..., None]
            pooled = (tokens * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9)
            for (key, _), vector in zip(batch, pooled):
                self.cache[key] = vector.astype(np.float32)
        result = np.asarray([self.cache[key] for key in keys])
        # Evict only after collecting the current request, including huge histories.
        while len(self.cache) > self.cache_limit:
            self.cache.popitem(last=False)
        return result


def _encoder():
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = Encoder()
    return _ENCODER


def _dense_rank(question, history, lexical):
    limit = int(os.environ.get("DENSE_CANDIDATE_LIMIT", "16"))
    if limit < 0:
        raise ValueError("DENSE_CANDIDATE_LIMIT must be nonnegative")
    if limit:
        candidates = [(si, ti) for _, si, ti in lexical[:limit]]
    else:
        candidates = [(si, ti) for si, session in enumerate(history["sessions"])
                      for ti in range(len(session["turns"]))]
    if not candidates:
        return []
    texts = [history["sessions"][si]["turns"][ti]["content"] for si, ti in candidates]
    model = _encoder()
    vectors = model.encode(texts)
    query = model.encode([question["question"]])[0]
    if not model.np.isfinite(vectors).all() or not model.np.isfinite(query).all():
        raise ValueError("non-finite embedding")
    # Avoid macOS Accelerate matmul floating-point warning behavior.
    similarities = model.np.einsum("ij,j->i", vectors, query)
    return sorted(((float(value), si, ti) for value, (si, ti) in zip(similarities, candidates)),
                  key=lambda row: (-row[0], row[1], row[2]))


def retrieve(question: dict, history: dict, k: int = 4, method: str = "dense",
             budget: int = 12000) -> list[dict]:
    """Return role-marked turn passages with dates from the current history.

    k counts turns, matching BM25. Equal RRF weights and constant 60 are fixed.
    MiniLM is symmetric: neither query nor passages take an instruction prefix.
    """
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; choose {METHODS}")
    if k < 1 or budget < 1:
        raise ValueError("k and budget must be positive")
    if not history["sessions"]:
        return []
    lexical = _rank(question, history)
    ranked = _dense_rank(question, history, lexical)
    if method == "dense-hybrid":
        fused = Counter()
        # Both sources rank precisely the same candidate pool.
        allowed = {(si, ti) for _, si, ti in ranked}
        for ranking in (ranked, [row for row in lexical if row[1:] in allowed]):
            for rank, (_, si, ti) in enumerate(ranking, 1):
                fused[si, ti] += 1 / (60 + rank)
        ranked = sorted(((value, si, ti) for (si, ti), value in fused.items()),
                        key=lambda row: (-row[0], row[1], row[2]))
    chosen = ranked[:k]
    cap = budget // max(len(chosen), 1)
    return [{"id": history["sessions"][si]["session_id"],
             "date": history["sessions"][si]["date"],
             "text": _excerpt(history["sessions"][si]["turns"][ti])[:cap]}
            for _, si, ti in chosen]
