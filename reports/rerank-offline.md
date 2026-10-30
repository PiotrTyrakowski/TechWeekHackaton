# Offline deterministic reranker screen

**Decision: reject this candidate for runtime use.** The implementation is retained as an isolated experiment, but it does not improve the useful evidence quality proxies over BM25 k=4.

## Method

`retrieval_rerank.py` starts from the existing BM25 turn ranking and adds a modest distinct-query-token coverage boost, an exact normalized query phrase boost, and a small verbosity penalty. It then keeps the highest-scoring turn from each session. It has no gold-data input. All configurations used the same 12,000-character budget. The evaluator's SHA-256 partition was retained; candidate selection was not tuned against validation.

## Full dev retrieval-set proxy results (526 questions)

| Config | Recall | Precision | F1 | All gold sessions | Mean packed chars | Mean latency |
|---|---:|---:|---:|---:|---:|---:|
| BM25 k=4 | 0.849 | 0.755 | 0.765 | 0.738 | 4,078 | 33.9 ms |
| BM25 k=8 | 0.922 | 0.546 | 0.642 | 0.849 | 6,812 | 33.7 ms |
| Rerank k=4 | 0.911 | 0.399 | 0.532 | 0.843 | 4,411 | 47.7 ms |
| Rerank k=8 | 0.952 | 0.226 | 0.351 | 0.907 | 9,122 | 47.7 ms |

At k=4, reranking gains 6.2 percentage points of recall over BM25, but loses 23.3 points of precision and 23.3 points of F1. It also takes 41% longer on average. At k=8 the recall gain is smaller while precision and F1 are substantially worse. These are retrieved session-set metrics, not Reactor-selected citations or answer accuracy.

## Exact answer retention diagnostic

Among 210 non-abstain questions where at least one answer/alias string (normalized, length at least three) occurs literally in the full gold session text, the string appeared in the retrieved excerpt for 80.0% with BM25 k=4 and 69.5% with rerank k=4. On the 174-question development partition the rates were 80.5% and 71.3%; on the 36-question validation partition they were 77.8% and 61.1%. This diagnostic is a literal packing/selection proxy, not answer accuracy. Generic yes/no and shorter strings were excluded.

## Artifacts

- `experiments/rerank-offline/summary.json` and per-configuration detail JSONL files: full dev metrics, fixed partition and category breakdowns.
- `experiments/rerank-offline/answer-retention.json`: exact answer retention counts and split rates.
- `tests/test_rerank_retrieval.py`: focused contract checks; not run in this screen.

Gold was read only by the evaluation scripts, after retrieval, for measurement.

## Coordinator verification

The two archived contract checks passed. A stricter reproducible retention audit
(`experiments/rerank-offline/audit_retention.py`) restricts excerpts to gold sessions
and uses official normalization plus phrase boundaries. On the same 210 eligible
questions, retention is 75.24% for BM25 and 65.71% for rerank. The earlier loose
substring values above are preserved as historical screen results; use the
stricter audit for comparisons. This remains a literal proxy, not answer accuracy.
The rejected implementation is archived inside the experiment directory and is
not registered in the runtime. Its original branch commit is 42ebc2e; the follow-up
audit commit is e5b3cd3.
