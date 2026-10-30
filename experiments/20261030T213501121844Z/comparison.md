# Lexical hybrid: reject

Command: `python3 evaluate.py --data data/dev --method bm25 --method hybrid --k 4 --k 8`

Hybrid is equal-weight reciprocal-rank fusion (constant 60) of BM25 and the
organizer's keyword-overlap turn ranking. No learned weights, external models,
API calls, or tuning on smoke-test answers. Existing methods were unchanged.

All 526 dev questions were evaluated; 496 answerable questions contribute to
evidence metrics. Fixed validation has 93 questions, 88 answerable. Percentages:

| Configuration | All recall | All precision | All F1 | Validation recall | Validation F1 | Mean text chars | Mean retrieval ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 k4 | 84.879 | 75.521 | 76.466 | 84.640 | 78.960 | 4078 | 30.18 |
| Hybrid k4 | 82.235 | 67.574 | 69.793 | 81.799 | 72.389 | 5408 | 45.24 |
| BM25 k8 | 92.164 | 54.631 | 64.152 | 94.640 | 68.897 | 6812 | 29.85 |
| Hybrid k8 | 90.306 | 46.286 | 56.856 | 92.670 | 61.303 | 8248 | 45.36 |

| Configuration | Multi-session recall / F1 (121 answerable) | Temporal recall / F1 (127 answerable) |
|---|---:|---:|
| BM25 k4 | 69.394 / 69.756 | 76.010 / 70.867 |
| Hybrid k4 | 64.105 / 63.187 | 72.297 / 65.812 |
| BM25 k8 | 84.201 / 68.779 | 86.024 / 64.403 |
| Hybrid k8 | 78.499 / 60.487 | 84.593 / 58.572 |

Hybrid improved per-question recall on 30 and worsened it on 55 questions at k4;
at k8 it improved 16 and worsened 41. All passage-text totals stayed within
12,000 characters. These text totals exclude the client's instructions and
source headers; runtime separately validates the complete 16,000-character message.

Examples of lost evidence: shampoo brand (`q_c0e2b39750ee`, k4), days attending
April events (`q_54cb8db2683d`, k4), total hiking distance
(`q_7ed4193f0c94`, k4), and days since meeting Emma (`q_8762cf18b347`, k8).

The observed longer passages and additional irrelevant sessions are consistent
with overlap ranking favoring long turns with common question words. This is an
inference, not a separately isolated causal experiment. Hybrid adds latency and
reduces recall and precision in both full dev and fixed validation: do not use it
for live runs. Retain BM25; BM25 k8 remains the next answer-level experiment once
Reactor is stable because it recovers more multi-session and temporal evidence.

F1 here treats every retrieved session as a citation. It is not answer accuracy
or Reactor-selected citation F1. This experiment made zero Reactor calls.
