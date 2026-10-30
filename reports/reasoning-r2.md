# Complementary reasoning R2

Do not promote: both question-derived candidates improve fixed-k evidence coverage, but lose too much citation precision. No runtime files were changed. The selected conservative candidate returns at most four sessions and adds at most one distinct session beyond the BM25 top-four-turn session set.

The two tested candidates preserve the original BM25 sessions, derive up to four event anchors by splitting explicit question clauses, and greedily add sessions using query-term novelty, anchor coverage and redundancy. The broader candidate fills all four session slots; the conservative candidate adds one. They use only the question text and supplied history, with no question-type/gold routing, model, network, event invention, or date arithmetic.

## Selection and scope

Both candidates were evaluated on development (433 questions / 408 answerable). Conservative was selected by development evidence F1: **71.40%** versus broader **67.84%**. Its full evaluation then included validation exactly once. No test data was accessed. Baselines are the existing full526 dense-full16 artifacts; their latency was recorded in separate runs.

Evidence F1 is a retrieval proxy that treats every retrieved session as cited. It is not Reactor answer accuracy. No supported-case exact-answer diagnostic was attempted, and no Reactor calls/resets/paid models were used.

| Method/scope | N | Answerable | Recall % | Precision % | F1 proxy % | All gold % |
|---|---:|---:|---:|---:|---:|---:|
| BM25 k4, all | 526 | 496 | 84.88 | 75.52 | 76.47 | 73.79 |
| BM25 k4, development | 433 | 408 | 84.93 | 74.80 | 75.93 | 74.51 |
| BM25 k4, validation | 93 | 88 | 84.64 | 78.88 | 78.96 | 70.45 |
| Dense hybrid k4, all | 526 | 496 | 85.73 | 82.36 | 80.77 | 73.39 |
| Dense hybrid k4, development | 433 | 408 | 85.21 | 81.13 | 79.81 | 72.79 |
| Dense hybrid k4, validation | 93 | 88 | 88.14 | 88.07 | 85.24 | 76.14 |
| Complementary conservative k4, all | 526 | 496 | 88.14 | 64.80 | 71.88 | 79.44 |
| Complementary conservative k4, development | 433 | 408 | 87.98 | 64.24 | 71.40 | 79.66 |
| Complementary conservative k4, validation | 93 | 88 | 88.84 | 67.42 | 74.09 | 78.41 |

## Full526 category metrics

| Method/category | N | Answerable | Recall % | Precision % | F1 proxy % | All gold % |
|---|---:|---:|---:|---:|---:|---:|
| BM25 k4, knowledge-update | 78 | 72 | 90.97 | 90.74 | 89.86 | 83.33 |
| BM25 k4, multi-session | 133 | 121 | 69.39 | 75.55 | 69.76 | 41.32 |
| BM25 k4, single-session-assistant | 112 | 112 | 100.00 | 76.12 | 83.10 | 100.00 |
| BM25 k4, single-session-user | 70 | 64 | 98.44 | 63.28 | 73.59 | 98.44 |
| BM25 k4, temporal-reasoning | 133 | 127 | 76.01 | 72.51 | 70.87 | 63.78 |
| Dense hybrid k4, knowledge-update | 78 | 72 | 89.58 | 95.37 | 91.02 | 80.56 |
| Dense hybrid k4, multi-session | 133 | 121 | 73.58 | 85.12 | 76.88 | 45.45 |
| Dense hybrid k4, single-session-assistant | 112 | 112 | 100.00 | 83.11 | 88.01 | 100.00 |
| Dense hybrid k4, single-session-user | 70 | 64 | 100.00 | 71.35 | 79.90 | 100.00 |
| Dense hybrid k4, temporal-reasoning | 133 | 127 | 75.35 | 77.23 | 72.73 | 59.06 |
| Complementary conservative k4, knowledge-update | 78 | 72 | 93.75 | 78.01 | 83.70 | 88.89 |
| Complementary conservative k4, multi-session | 133 | 121 | 76.65 | 62.40 | 66.72 | 54.55 |
| Complementary conservative k4, single-session-assistant | 112 | 112 | 100.00 | 71.65 | 79.79 | 100.00 |
| Complementary conservative k4, single-session-user | 70 | 64 | 98.44 | 55.60 | 67.92 | 98.44 |
| Complementary conservative k4, temporal-reasoning | 133 | 127 | 80.24 | 58.20 | 65.10 | 70.08 |

## Size, latency and paired changes

Selected candidate: mean 32.79 ms, p95 36.72 ms; mean 7878 packed characters and 2.62 unique sessions. Budget remains 12,000 text characters; k remains four. Two strongest turns plus fitting neighbors are packed per session with source IDs, source dates and explicit roles.

| Baseline, answerable scope | Recall win/loss/tie | F1 win/loss/tie | All-gold win/loss/tie |
|---|---:|---:|---:|
| bm25-k4, all (496) | 40/0/456 | 40/191/265 | 28/0/468 |
| bm25-k4, development (408) | 32/0/376 | 32/156/220 | 21/0/387 |
| bm25-k4, validation (88) | 8/0/80 | 8/35/45 | 7/0/81 |
| dense-hybrid-k4, all (496) | 48/21/427 | 55/245/196 | 41/11/444 |
| dense-hybrid-k4, development (408) | 42/16/350 | 48/198/162 | 36/8/364 |
| dense-hybrid-k4, validation (88) | 6/5/77 | 7/47/34 | 5/3/80 |

The coverage gain is not merely higher k: duplicate turn slots are converted to complementary source sessions while the cap stays four. However, count/order wording also occurs in single-session questions. Those questions gain unnecessary sessions, while aggregate questions can still require more than four sources. The experiment does not meet the precision-preservation objective, so the existing dense/BM25 pipeline should remain selected.

Validation: six dependency-free unit tests passed, covering complementary anchors, strict history-local IDs and dates, text budgets including tiny budgets, explicit roles at normal budgets, input immutability, no cross-history cache contamination, gold/type independence, and invalid/empty inputs.

Artifacts: `experiments/reasoning-r2/comparison.json` contains all full/split/category metrics and paired win/loss counts; `development/` contains both development candidates; `final/` contains the one selected full evaluation. `report_results.py` only summarizes completed artifacts.
