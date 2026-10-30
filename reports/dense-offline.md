# Offline MiniLM reranking experiment — 2026-10-30

## Scope and outcome

Implemented an optional local embedding retriever in `retrieval_dense.py`, with `dense` (cosine reranking) and `dense-hybrid` (equal-weight BM25/cosine reciprocal-rank fusion, constant 60). **The measured configurations rerank a BM25 top-16-turn shortlist. They are not exhaustive semantic retrieval.** The fixed shortlist and fusion settings were selected on computational grounds before inspecting validation outcomes.

No Reactor invocation, history reset, paid model API, credential read, answer generation, or submission was performed. Gold is read by the measurement harness after retrieval and never influences retrieval, candidate construction, query encoding, or embedding caching. Evidence metrics are unique-session retrieval proxies, not answer accuracy and not actual Reactor-selected citation F1.

## Model and implementation

- Model: `Xenova/all-MiniLM-L6-v2`, pinned revision `751bff37182d3f1213fa05d7196b954e230abad9`; quantized ONNX file `onnx/model_quantized.onnx` (23MB).
- Underlying model: `sentence-transformers/all-MiniLM-L6-v2`. Its first-party [model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) specifies 384-dimensional sentence vectors, attention-mask-aware mean pooling, L2 normalization, and a 256-wordpiece default input limit. This symmetric encoder uses raw question/turn text, without query/passage instruction prefixes.
- The export is published in the [maintainer's pinned repository](https://huggingface.co/Xenova/all-MiniLM-L6-v2/tree/751bff37182d3f1213fa05d7196b954e230abad9/onnx). Python ONNX Runtime runs its token output locally on CPU; we apply the pooling/normalization described above.
- Model SHA256: `afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1`.
- Tokenizer SHA256: `da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0`.
- Dependencies tested: Python 3.12.13, numpy 2.2.6, onnxruntime 1.22.1, tokenizers 0.21.4. See `requirements-dense.txt`.
- Batch size 16; maximum 256 tokens; CPU provider; two threads for pilot, four threads for full comparison; ONNX inter-op threads 1.
- Embeddings cache by SHA256 of text, bounded to 50,000 entries. Dates are always looked up from the current history, never cached with text/session embeddings. No history mutation occurs.
- Returned passages preserve the turn's `user:`/`assistant:` role. `k` counts turns, matching existing BM25. Character budget remains 12,000 total passage characters; each selected turn receives an equal cap.

## Setup and feasibility

The existing Hugging Face cache had GPT-2-family models, without a suitable sentence embedding model. Cached uv packages and installed Python versions were inspected before downloading. The new model plus dependency downloads were approximately 70MB, below the 300MB limit; setup completed in substantially less than three minutes.

Dataset inventory: 470 referenced histories, 231,877 turn instances, 180,934 unique turn texts. A 128-turn CPU encoding probe took 6.71 seconds with two threads. Extrapolating without batching/cache improvements gives about 2.6 hours for exhaustive unique-turn encoding, outside this experiment's time bound. This is a cost estimate, not a measured full-index build. A BM25 top-16 shortlist made the paired run practical.

The initial 24-question pilot used only development questions: ascending SHA256(question_id), taking the first 24 after the existing 80/20 hash partition. It took 28.79 seconds total at two threads. Full comparison uses all 526 questions with the unchanged existing partition: 433 development, 93 validation. Gold-abstaining questions are excluded from evidence metrics and remain included in latency/size metrics.

## Pilot, development-only n=24

| Method | k | Recall % | Precision % | Session F1 % | All-hit % |
|---|---:|---:|---:|---:|---:|
| BM25 | 4 | 92.42 | 87.12 | 86.06 | 86.36 |
| Dense rerank, shortlist16 | 4 | 84.09 | 87.12 | 82.73 | 68.18 |
| Dense hybrid, shortlist16 | 4 | 92.42 | 87.12 | 87.12 | 86.36 |
| BM25 | 8 | 98.48 | 59.32 | 71.21 | 95.45 |
| Dense rerank, shortlist16 | 8 | 97.73 | 70.91 | 78.31 | 95.45 |
| Dense hybrid, shortlist16 | 8 | 97.73 | 74.55 | 80.74 | 95.45 |

The pilot suggests hybrid ranking concentrates selected turns in fewer sessions at k=8. This can improve the retrieval-session F1 proxy while slightly reducing recall. It does not establish improved answer behavior.

Pilot source used NumPy matrix multiplication and emitted macOS Accelerate floating-point warnings; the final implementation uses explicit `einsum` for cosine scores and rejects non-finite vectors. The pooling/normalization procedure is unchanged. Full-run results use this final implementation.

## Reproduction

```sh
uv venv --python 3.12 .venv-dense
uv pip install --python .venv-dense/bin/python -r requirements-dense.txt
.venv-dense/bin/python experiments/dense-fetch-model.py
.venv-dense/bin/python -m unittest tests/test_dense_retrieval.py
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4 \
DENSE_THREADS=4 DENSE_CANDIDATE_LIMIT=16 \
.venv-dense/bin/python experiments/dense-run.py --sample 0 --out experiments/dense-full16
```

Set `DENSE_MODEL_DIR` to reuse the downloaded asset directory from another working directory. Retrieval never downloads weights automatically. `DENSE_CANDIDATE_LIMIT=0` enables exhaustive history-turn scoring, at substantial initial embedding cost. The module default is 16; all measured experiments also explicitly set 16.

Artifacts contain per-question paired records, fixed split labels, model/code/data SHA256 hashes, settings, passage character counts, unique sessions, mean/p95 latency, and the exact measured runtime. Cold model/document encoding cost is charged to dense-k4; dense-k8 and hybrid passes reuse the in-process cache. Compare end-to-end runtime as well as warm per-variant latency.

The full run began at `2026-10-30T22:08:03Z` (log creation timestamp). Model assets remain at `/private/tmp/rxai-dense-20261030/experiments/dense-model`. Embedding vectors are only in-process memory, not persisted; a later process must encode its shortlisted texts again. Large model files are deliberately not committed.

## Full results

Full run finished in **346.25 seconds** with four CPU threads and zero Reactor calls. Summary: `experiments/dense-full16/summary.json`; paired details are adjacent JSONL files.

| Split | Method | k | Recall % | Precision % | Session F1 % | All-hit % |
|---|---|---:|---:|---:|---:|---:|
| all | bm25 | 4 | 84.88 | 75.52 | 76.47 | 73.79 |
| all | bm25 | 8 | 92.16 | 54.63 | 64.15 | 84.88 |
| all | dense | 4 | 83.24 | 82.76 | 79.86 | 69.56 |
| all | dense | 8 | 92.39 | 63.76 | 70.80 | 84.88 |
| all | dense-hybrid | 4 | 85.73 | 82.36 | 80.77 | 73.39 |
| all | dense-hybrid | 8 | 93.03 | 61.74 | 69.84 | 86.09 |
| development | bm25 | 4 | 84.93 | 74.80 | 75.93 | 74.51 |
| development | bm25 | 8 | 91.63 | 53.55 | 63.13 | 84.31 |
| development | dense | 4 | 82.63 | 81.52 | 78.78 | 68.63 |
| development | dense | 8 | 91.88 | 62.44 | 69.58 | 84.31 |
| development | dense-hybrid | 4 | 85.21 | 81.13 | 79.81 | 72.79 |
| development | dense-hybrid | 8 | 92.56 | 60.79 | 68.90 | 85.54 |
| validation | bm25 | 4 | 84.64 | 78.88 | 78.96 | 70.45 |
| validation | bm25 | 8 | 94.64 | 59.66 | 68.90 | 87.50 |
| validation | dense | 4 | 86.04 | 88.54 | 84.84 | 73.86 |
| validation | dense | 8 | 94.73 | 69.85 | 76.42 | 87.50 |
| validation | dense-hybrid | 4 | 88.14 | 88.07 | 85.24 | 76.14 |
| validation | dense-hybrid | 8 | 95.25 | 66.15 | 74.21 | 88.64 |

| Method | k | Mean chars | Mean unique sessions | Mean latency ms | P95 latency ms |
|---|---:|---:|---:|---:|---:|
| bm25 | 4 | 4078.03 | 2.14 | 28.78 | 32.33 |
| bm25 | 8 | 6811.53 | 3.64 | 28.37 | 29.65 |
| dense | 4 | 3836.25 | 1.86 | 497.92 | 649.18 |
| dense | 8 | 6495.10 | 3.08 | 38.25 | 44.93 |
| dense-hybrid | 4 | 3895.14 | 1.94 | 32.94 | 39.93 |
| dense-hybrid | 8 | 6552.04 | 3.24 | 29.67 | 35.26 |

Latency rows are ordered: BM25-k4, BM25-k8, dense-k4, dense-k8, hybrid-k4, hybrid-k8. Thus the first dense pass includes model/document encoding and subsequent variants are warm-cache timings. These are not six independent cold-run performance measurements.

| Split | Comparison | Paired F1 wins | Losses | Ties | Mean delta pp |
|---|---|---:|---:|---:|---:|
| development | dense-k4 vs BM25-k4 | 110 | 69 | 229 | +2.85 |
| development | dense-k8 vs BM25-k8 | 188 | 49 | 171 | +6.46 |
| development | dense-hybrid-k4 vs BM25-k4 | 93 | 32 | 283 | +3.88 |
| development | dense-hybrid-k8 vs BM25-k8 | 165 | 29 | 214 | +5.77 |
| validation | dense-k4 vs BM25-k4 | 33 | 13 | 42 | +5.88 |
| validation | dense-k8 vs BM25-k8 | 40 | 9 | 39 | +7.52 |
| validation | dense-hybrid-k4 vs BM25-k4 | 26 | 5 | 57 | +6.28 |
| validation | dense-hybrid-k8 vs BM25-k8 | 30 | 2 | 56 | +5.31 |

## Interpretation and recommendation

`dense-hybrid`, shortlist16, k=4 is the strongest fixed configuration for mean session F1 in this comparison: +3.88 percentage points on development and +6.28 points on validation relative to BM25-k4. Validation recall also rises from 84.64% to 88.14%, with 26 paired F1 wins and 5 losses among 88 answerable validation questions. Across all answerable questions recall rises from 84.88% to 85.73%, while all-hit changes from 73.79% to 73.39%; the development all-hit regression should remain visible when choosing a runtime retriever. This is a candidate for a later authorized answer-generation test, not proof of improved answers.

For a recall-first fixed k=8 configuration, hybrid reaches 93.03% all-scope recall and 95.25% validation recall. Its mean session F1 is lower than k=4 because more distinct sessions count as retrieved citations in this proxy. Dense-only reranking at k=4 loses all-scope recall and should not replace the balanced hybrid on these results.

The standalone hybrid should budget approximately the first dense pass's embedding cost, rather than its warm 33ms ranking row. This run used no persisted vector cache; selecting just one configuration in a new process entails encoding its BM25 candidates again. The 50,000-entry in-memory cache is substantially larger than this run's shortlist workload.

For code provenance, the module's fallback shortlist was changed from 64 to 16 during the full run so future invocations match the tested setup. The running process explicitly had `DENSE_CANDIDATE_LIMIT=16` throughout, so this fallback-only edit did not alter any measured ranking or configuration. No parameter was adjusted after validation inspection. Full artifacts record source SHA256 hashes of the final equivalent configured implementation.

## Verification

All 40 repository tests pass in the optional environment after installing the existing base `websockets==15.0.1` requirement, including three added dense contract tests. The dense tests cover history-local dates across repeated calls, the shared passage character budget, retained role labels, hybrid output, argument validation, and empty histories. Existing client/runtime tests use mocks; no service invocation occurred.
