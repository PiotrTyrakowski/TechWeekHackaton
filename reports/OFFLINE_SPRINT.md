# Parallel offline retrieval sprint — 2026-10-30

Three isolated Git worktrees ran dense retrieval, deterministic reranking, and
specialized session coverage in parallel; the coordinator handled integration,
paired evaluation, and acceptance checks. User instructions kept all Reactor
requests and history resets disabled. **Zero Reactor calls and zero paid model
calls were made.** A small public ONNX model and optional dependencies required
approximately 70 MB of free downloads.

Herdr inventory found no running named session: the inherited `agent-factory`
context was stopped, with only `default` active. No panes were launched in default.
Available task agents used separate `/private/tmp/rxai-*-20261030` worktrees;
native agents had clear file ownership, model/reasoning assignments, and time
bounds. Routine reranking used a cheaper agent. Completed/rejected workstreams
are stopped; worktrees retain their reproducible experiment branches.

## Measured comparison

All full runs cover 526 dev questions, including 496 answerable. Passage text
budget is 12,000 characters. The deterministic hash split is 433 development and
93 validation questions, including 408 and 88 answerable respectively. The split
is reused exploratory development validation, not a pristine final holdout.
Dev-large contains the same questions and was not treated as another holdout.

| Candidate | Session recall | Retrieval F1 proxy | All gold sessions | Validation F1 proxy |
|---|---:|---:|---:|---:|
| BM25, 4 turns | 84.88% | 76.47% | 73.79% | 78.96% |
| BM25, 8 turns | 92.16% | 64.15% | 84.88% | 68.90% |
| Dense/BM25 fusion, 4 turns | 85.73% | **80.77%** | 73.39% | **85.24%** |
| Dense/BM25 fusion, 8 turns | 93.03% | 69.84% | 86.09% | 74.21% |
| Adaptive session pool, k4 | **94.64%** | 41.21% | **89.72%** | 41.85% |
| Rejected generic reranker, k4 | 91.10% | 53.2% | 84.3% | see archived details |

F1 here treats every retrieved session as a citation. Reactor can cite a subset;
these numbers are **not answer accuracy or actual Reactor evidence F1**.

## Decisions

- Integrate optional `dense-hybrid` as the strongest balanced fixed candidate for
  a later answer experiment: mean F1 proxy gains 4.31 percentage points overall,
  3.88 on development, and 6.28 on validation versus BM25-4. Validation has 26
  paired F1 wins and 5 losses. All-gold recovery slightly declines overall, so do
  not silently promote it on answer quality claims.
- Retain BM25-4 as the lightweight runner default. BM25-8 and dense-hybrid-8 are
  useful recall/precision alternatives to test after exclusive Reactor access.
- Integrate `adaptive` only as an experimental high-recall evidence pool. It
  improves recall on 101 questions and loses none versus BM25-4, but greatly
  reduces precision. Multi-session recall is 89.59%, temporal 90.18%, and update
  99.31%. Its larger context needs selective answering and citations.
- Reject the generic coverage/diversity reranker. On 210 literal-answer-eligible
  questions, the stricter phrase-retention audit falls from 75.24% with BM25 to
  65.71%. Its code is archived with experiment artifacts, not runtime registration.
- Adaptive k8/16-session coverage raises recall to 97.60% but drives F1 proxy to
  24.85%; it is not recommended over the more balanced alternatives.

## Cost and implementation limits

Dense fusion is a **reranker of BM25's top 16 turns**, not exhaustive semantic
search. MiniLM weights, tokenizer, and revision are pinned; no remote embedding or
reranking service is used. The six-configuration paired full run took 346 seconds
with four CPU threads. Its first dense pass averages about 498 ms including
embedding work; later hybrid rows reuse embeddings and average about 33 ms.
Budget around the cold embedding cost for a standalone hybrid process, not the
warm timing. BM25 averages roughly 30 ms. No persistent vector index was built.

Gold is used only after retrieval for scoring. Ranking does not consume gold,
gold question types, aliases, or evidence IDs. IDs and dates always come from the
current history. Optional dependencies load only when a dense method is selected;
missing packages/assets fail before any Reactor request. A nonmatching lexical
shortlist returns empty instead of unexpectedly encoding an entire history.
None of the measured 526 questions had an empty lexical shortlist, so this
integration safeguard does not alter reported measurements.

## Acceptance and reproduction

- Unified integrated BM25/adaptive full-526 evaluation reproduced the agent's
  metrics. The common comparison script recomputes metrics from per-question
  session IDs for nine configurations and validates question coverage, gold IDs,
  and partition agreement rather than mixing incompatible summaries.
- All 47 standard-library/base-environment tests pass; two additional archived
  reranker checks pass. An actual local-embedding runtime dry run matched the
  full-run evidence IDs for the representative cat-name question, with a
  5,670-character wrapper message and no API invocation.
- Independent conservative size audit covers all 526 questions at the full
  12,000-character budget with 16 passage headers: maximum 14,642 of 16,000
  characters. Forty actual sampled configurations passed date, ID, role, gold
  independence, and size checks. This is a conservative bound plus sampled actual
  validation, not a claim that all model outputs were generated twice.

Run `python experiments/offline-sprint/compare.py` to recreate the common report
from committed paired records without repeating model inference. Use README's
optional setup and `experiments/dense-run.py --sample 0` for a fresh dense run.
The run scripts, settings, model/data/code hashes, and full question-level
artifacts are committed. Model weights, environments, and runtime caches stay local.

Reports: `dense-offline.md`, `specialized-offline.md`, `rerank-offline.md`, and
`specialized-packing-audit.json`. Unified metrics and paired wins/losses:
`experiments/offline-sprint/comparison.json`.

Next gate: coordinate exclusive access to the shared stateful Reactor agent,
validate one correctly cited answer, then compare the fixed candidates on a small
paired answer sample. **No Reactor calls are authorized by this offline sprint.**
