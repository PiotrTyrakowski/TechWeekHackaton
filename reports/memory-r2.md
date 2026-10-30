# Structured memory R2: rejected after holdout

The deterministic fact-memory candidate improved mean session-evidence F1 on development by **0.78 percentage points** versus dense-hybrid-4, but lost **6.43 points on the fixed holdout**. Do not promote it. These are retrieval proxies, not answer accuracy; no Reactor, resets, credentials, paid models, network requests, or new dependencies were used.

## Implementation and boundary

`retrieval_memory.py` provides `retrieve(question, history, k=4, method='memory', budget=12000)`. It receives only the question and current history. It never opens gold or question-split files. Output IDs and dates come from the current history, while snippets retain role and source turn IDs. Dates are absent from the content cache.

Two candidates were screened:

1. `memory`: sentence/clause BM25 memory, consolidated into distinct sessions, with a small second-sentence support bonus.
2. `memory-facts`: the same memory with user-assertion weights and a development-calibrated relative score cutoff. Quantitative/time queries use a 0.55 cutoff relative to the top session, other queries 0.75; `k` is an upper bound.

The memory is prepared once per history into sentence cards and an inverted lexical index before scoring queries. A bounded 4096-turn LRU caches immutable content, never dates. The index remains in process for the current history; there is no persisted cross-run index. This preserves a small dependency footprint but makes cold queries slower than the existing BM25 baseline. At most six relevance-ranked cards per selected session are packed in source order. Source snippets are contiguous substrings, including original whitespace between short merged clauses.

## Protocol

The fixed split is 433 development questions (408 answerable) and 93 validation questions (88 answerable), as defined in `evaluate.partition`. Development gold was used only by calibration/audit scripts under `experiments/memory-r2`; retrieval uses no gold. Both candidate screens used development only. The sentence candidate was stopped immediately. For fact-memory, 12 global cutoff values were screened, then a small 42-pair two-cutoff grid was calibrated on development. The selected policy was frozen before one holdout evaluation. The holdout was not used for further tuning. This calibration breadth and the failed holdout indicate overfitting rather than a reliable gain.

The baseline numbers below come from `reports/dense-offline.md` and `experiments/offline-sprint/comparison.json`. The evaluator defines F1 as all selected session IDs treated as citations, excluding unanswerable questions. It does not measure answer correctness or downstream citation selection.

## Aggregate results

All evidence metrics are percentages. `All gold` requires every gold session ID to be retrieved.

| Split / candidate | Recall | Precision | F1 proxy | All gold | Characters | Sessions | Cold mean / p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| Development sentence memory, 4 sessions | 88.79 | 38.28 | 51.25 | 80.88 | 3009 | 3.98 | 75.94 / 105.57 |
| Development fact memory, 4 sessions before cutoff | 90.57 | 39.44 | 52.60 | 83.58 | 2935 | 3.98 | warm 0.26 / 0.64 |
| Development frozen fact memory | 85.00 | 82.01 | 80.59 | 72.79 | 1633 | 2.08 | 75.23 / 103.93 |
| Development dense-hybrid-4 | 85.21 | 81.13 | 79.81 | 72.79 | — | — | — |
| Validation frozen fact memory | 86.84 | 77.84 | 78.81 | 76.14 | 1753 | 2.27 | 89.84 / 136.19 |
| Validation dense-hybrid-4 | 88.14 | 88.07 | 85.24 | 76.14 | — | — | — |
| Validation BM25-4 | 84.64 | 78.88 | 78.96 | 70.45 | 3790 | 2.05 | 38.40 / 47.71 |

The first two screens shared an index, explaining the warm second-method timing. Frozen evaluations used one method and include preprocessing. Fixed 4-session memory inflated recall by retrieving more distinct sessions and badly harmed precision. The calibrated candidate reduced that inflation, but its validation precision still fell below both balanced baselines. It did not retrieve more complete validation evidence than dense-hybrid.

Frozen development evaluation took 34.06 s wall time (33.86 s user CPU), maximum RSS **117,571,584 bytes** (~112.1 MiB). This includes dataset loading/evaluator overhead. Exact `/usr/bin/time -l` output is retained in `experiments/memory-r2/frozen-development-resources.txt`.

The separate development audit prepared **1,663,921 cards over 393 histories** in 44.16 s under concurrent machine load; warm query scoring/packing took 0.209 s for 433 questions (~0.48 ms/query). These timings are from a separate pass and should not be added to the 34.06 s evaluation.

The development-only answer-span audit found an exact normalized gold answer or alias in the selected full sessions for **226/408** answerable questions, versus **192/408** in the packed cards: **84.96% conditional span retention**. This is a literal span diagnostic, not answer accuracy, and shows meaningful content loss from sentence packing. Arithmetic/temporal answers often are not verbatim anywhere, so this metric cannot measure their answerability. Compact output alone does not justify deployment.

## Category results

| Split | Category | Questions | Recall | Precision | F1 proxy | All gold |
|---|---|---:|---:|---:|---:|---:|
| Development | knowledge-update | 62 | 84.48 | 94.68 | 87.36 | 68.97 |
| Development | multi-session | 109 | 73.40 | 74.91 | 71.55 | 48.45 |
| Development | single-session-assistant | 94 | 100.00 | 89.27 | 91.99 | 100.00 |
| Development | single-session-user | 60 | 98.18 | 88.18 | 90.79 | 98.18 |
| Development | temporal-reasoning | 108 | 75.56 | 71.71 | 69.56 | 59.62 |
| Validation | knowledge-update | 16 | 92.86 | 94.05 | 92.62 | 85.71 |
| Validation | multi-session | 24 | 74.86 | 71.53 | 69.91 | 50.00 |
| Validation | single-session-assistant | 18 | 100.00 | 81.02 | 85.37 | 100.00 |
| Validation | single-session-user | 10 | 100.00 | 78.70 | 84.07 | 100.00 |
| Validation | temporal-reasoning | 25 | 80.22 | 71.74 | 72.49 | 69.57 |

Question counts include unanswerable questions; metrics exclude them. The main failure remains choosing the correct number of supporting sessions for arithmetic, updates, and time relationships. A cheap personal-assertion heuristic does not replace semantic retrieval or temporal interpretation.

## Artifacts and reproduction

- Initial development screen: `experiments/memory-r2/20261030T222624021076Z/`.
- Frozen development: `experiments/memory-r2/frozen-development/20261030T222903785223Z/`.
- Single holdout: `experiments/memory-r2/holdout/20261030T222847014930Z/`.
- Calibration scripts and rank records: `experiments/memory-r2/calibrate.py`, `policy-calibration.py`, `development-ranks.json`, `policy-calibration.json`.
- Development-only packing/preprocessing audit: `experiments/memory-r2/packing-audit.py` and `.json`.

The only post-evaluation code correction preserves original whitespace when joining adjacent short clauses, rather than inserting a space. It preserves token counts/ranking semantics and makes packed source snippets verbatim. Recorded character/timing figures precede this formatting correction. No additional holdout scoring or tuning followed it.

```sh
PYTHONPATH=$PWD /Users/zoga/Dev/Playground/TechWeekHackaton/.venv/bin/python /Users/zoga/Dev/Playground/TechWeekHackaton/evaluate.py \
  --data data/dev --questions experiments/offline-sprint/development-questions.jsonl \
  --retriever-module retrieval_memory --method memory-facts --k 4 --out experiments/memory-r2
/Users/zoga/Dev/Playground/TechWeekHackaton/.venv/bin/python -m unittest tests.test_memory_retrieval
```

Five tests pass, covering provenance, local-date cache isolation, distinct sessions, budgets, invalid config/empty history, and verbatim snippets including decimals and newlines. Dev-large was not run: it shares development questions and would add scale cost after a failed holdout rather than establish generalization.
