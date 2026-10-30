# Specialized offline retrieval experiment

Question-text routing improves session evidence coverage, but loses substantial citation precision. Keep `adaptive` as an experimental high-recall evidence-pool option; retain BM25 as the default. No Reactor calls, credentials, resets, or paid model calls were used. These are retrieval diagnostics, not answer-accuracy results.

## Methods and selection

Two deterministic candidates were screened on the fixed question-ID-hash development partition (433 questions, 408 answerable). Neither consumes gold, question type, answers, aliases, or evidence IDs at retrieval time.

- `session`: rank sessions by their best BM25 turn and retrieve four distinct sessions. Session ranking intentionally matches the existing `bm25-context` approach; the change is packing.
- `adaptive`: use four distinct sessions normally and eight when question wording indicates counts, aggregation, chronology, or updates. Routing uses a fixed regex over question text. It does not use dates to favor recent sessions: comparisons and historical questions need earlier evidence too.

Each selected session packs its two strongest matching turns before adjacent dialogue, in chronological turn order. Long matching turns receive a contiguous query-centered excerpt. Role labels, history-local session IDs, and history-local dates are preserved. The total passage text stays within the requested character budget, including tiny budgets.

Development screening selected `adaptive` for the narrow objective of maximizing all-gold-session coverage. No parameter was adjusted after seeing validation. `session` has no new session-recall benefit over the existing context baseline; it is retained as a packing/control candidate.

| Development candidate | Recall | Precision | F1 proxy | All gold | Mean chars | Mean ms |
|---|---:|---:|---:|---:|---:|---:|
| session k4 | 90.89% | 39.75% | 52.95% | 84.07% | 9,186 | 37.48 |
| adaptive k4 | 94.35% | 27.40% | 41.07% | 89.46% | 9,673 | 38.94 |

## Full evaluation and paired baseline

The chosen method was evaluated once on all 526 questions (496 answerable), including the untouched validation partition of 93 questions (88 answerable). Baseline details were paired by question ID from the existing full-526 BM25 k4 run; source path and SHA256 are recorded in `paired-bm25.json`. Latencies were measured in separate local runs and are descriptive rather than controlled benchmarks.

| Full 526 | Recall | Precision | F1 proxy | All gold | Mean chars | Mean ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 k4 | 84.88% | 75.52% | 76.47% | 73.79% | 4,078 | 30.38 | 31.51 |
| adaptive k4 | 94.64% | 27.50% | 41.21% | 89.72% | 9,668 | 36.17 | 48.09 |
| BM25 k8 reference | 92.16% | 54.63% | 64.15% | 84.88% | 6,812 | 29.98 | 31.14 |

Adaptive retrieves 6.49 unique sessions on average. Against BM25 k4, per-question session recall improves on 101 questions and declines on none; all-gold coverage improves on 79 and declines on none. F1 proxy improves on 44 questions and declines on 422. The coverage increase is expected from selecting a superset of baseline sessions and should not be mistaken for improved ranking quality.

Validation alone: adaptive recall 96.00%, precision 27.98%, F1 proxy 41.85%, all-gold coverage 90.91%; BM25 k4 recall 84.64%, precision 78.88%, F1 proxy 78.96%, all-gold coverage 70.45%.

| Question category (reporting only) | BM25 k4 recall | Adaptive recall | Adaptive F1 proxy | Adaptive all gold |
|---|---:|---:|---:|---:|
| Multi-session | 69.39% | 89.59% | 45.68% | 76.03% |
| Temporal reasoning | 76.01% | 90.18% | 39.73% | 84.25% |
| Knowledge update | 90.97% | 99.31% | 49.35% | 98.61% |
| Single-session assistant | 100.00% | 100.00% | 36.03% | 100.00% |
| Single-session user | 98.44% | 98.44% | 35.59% | 98.44% |

This method is useful only if downstream answering can select a small number of supported citations from a broader evidence pool. There is no answer-generation experiment here to establish that benefit. BM25 k8 offers a stronger precision/cost tradeoff for only 2.48 percentage points less recall. Gold-session coverage also does not establish whether the packed excerpts contain the answer-bearing words.

## Artifacts and validation

- `experiments/specialized-shortlist/20261030T220703410964Z/`: development-only candidate details and summaries.
- `experiments/specialized-full/20261030T220751202290Z/`: full chosen-method details, summary, and paired baseline comparison by partition/category.
- `python3 -m unittest tests.test_specialized_retrieval`: five tests passed, covering routing independence from extra gold-like fields, chronology neutrality, unique sessions, valid local dates/IDs, strict budgets, long-turn query neighborhoods, empty retrieval, and invalid arguments.

Reproduce the chosen run with the root evaluator that supports external retriever modules:

```sh
PYTHONPATH=$PWD /Users/zoga/Dev/Playground/TechWeekHackaton/.venv/bin/python /Users/zoga/Dev/Playground/TechWeekHackaton/evaluate.py --data data/dev --retriever-module retrieval_specialized --method adaptive --k 4 --out experiments/specialized-full
```
