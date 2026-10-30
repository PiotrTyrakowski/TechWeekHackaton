# BM25-4 live smoke — interrupted

Selected five answerable questions, one per category, by the existing fixed
question-ID hash ordering. All five gold evidence session sets are present in
BM25-4 packed evidence. No answers or citations were edited.

**Status: 1/5 completed.** API history replacement prevents completing the rest.
No 526-question Reactor run was launched.

Official scorer command actually run:

```sh
.venv/bin/python official/score.py reports/live-smoke-20261030T2135/completed-gold.jsonl reports/live-smoke-20261030T2135/predictions.jsonl --details reports/live-smoke-20261030T2135/official-score-details.jsonl
```

Completed-only results: **1 correct, 0 wrong, 0 unjudged; evidence F1 0.000**.
There are no unjudged answers requiring manual adjudication. Manual inspection
also confirms the completed answer exactly matches gold. Four unresolved
questions are incomplete, not evaluated final wrong answers.

| Question ID | Category | Reactor prediction | Gold | Submitted citations |
|---|---|---|---|---|
| q_d4ead82e5cad | user | Luna | Luna | [] |
| q_e2cc79359e15 | assistant | no answer; closed | Atmospheric distillation, fluid catalytic cracking (FCC), alkylation, and hydrotreating. | none |
| q_6eaf85dde884 | multi-session | not attempted | 5 | none |
| q_61a19ce280f4 | update | not attempted | Yes. | none |
| q_53ebfc7819cf | temporal | not attempted | 15 | none |

The completed Reactor response cites `[E1]` in its explanatory text, mapped to
`s_8a377a1e6a80`, but its marked final answer is only `Luna`. The official client
extracts citations from the marked answer, yielding `[]`. We preserve this result
and its zero evidence score. A future prompt should explicitly require citation
labels on the final-answer line, rather than moving narrative citations ourselves.

Completed answer Reactor latency: **46.63 s**; client wall time **46.92 s**.
Total wall time inside recorded client attempts: **56.45 s**. The snapshot records
**7 API operations: 3 reset requests + 4 question attempts**, with **0 internal
safe retries**. Three question attempts failed: `closed`, `history_changed`,
`closed`. The first closed call took 1.14 s, refused call 0.70 s, second closed call
5.37 s. The server replaced the history after returning a successful reset.
Closure reasons were not included in the client's JSON; future failures retain
redacted client stderr too.

The runner preserved the first raw answer from the durable attempt without
re-asking it. One explicit closed retry and one recovery reset were attempted.
No additional API calls run while waiting to establish exclusive access to our
agent or resolution of a Reactor server fault.

## Retrieval follow-up, offline only

The full 526-question comparison rejects equal-weight BM25/keyword RRF hybrid:
BM25-4 recall/F1 84.88%/76.47% versus hybrid-4 82.23%/69.79%; BM25-8
92.16%/64.15% versus hybrid-8 90.31%/56.86%. Hybrid is slower and packs more text.
Validation agrees; see `experiments/20261030T213501121844Z/comparison.md`.

BM25-8 raises multi-session recall from 69.39% to 84.20% and temporal recall from
76.01% to 86.02%, at the same 12,000-character text budget. Reactor can cite a
subset, so lower retrieval-set F1 alone does not reject BM25-8. Actual answer
accuracy remains unproven. Finish this smoke test first, then use a small paired
answer experiment with final-line citation instructions and difficult development
questions. Do not use these five successful retrieval cases alone to select k.
