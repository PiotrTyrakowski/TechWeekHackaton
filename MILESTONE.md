# First baseline milestone — 2026-10-30

Implemented reproducible data setup, exact official keyword baseline, stdlib turn
BM25, distinct-session BM25 context packing, offline evaluation, and a sequential
checkpointed Reactor runner using the official client and prediction adapter.

Full dev experiment: **526 questions; 496 answerable**, 12,000-character passage
budget. No Reactor calls or external model calls. All values below are session
retrieval metrics, not answer accuracy or actual Reactor citation F1.

| Retrieval | Recall | Precision | Retrieval-set F1 |
|---|---:|---:|---:|
| Official keyword, 4 turns | 73.63% | 54.23% | 58.22% |
| BM25, 4 turns | 84.88% | 75.52% | 76.47% |
| BM25, 8 turns | 92.16% | 54.63% | 64.15% |
| BM25, 12 turns | 94.66% | 39.15% | 51.35% |

BM25 at four turns improves F1 by **18.25 percentage points** and recall by
**11.25 points** over official keyword retrieval. Mean latency is ~30 ms, with
~4,078 passage characters. All gold sessions are recovered on 73.79% of answerable
questions, compared with 60.89% for the official baseline.

Fixed validation partition: 93 questions, 88 answerable; BM25 four-turn recall
84.64%, F1 78.96%. The partition was fixed by question-ID hash before evaluation.
Both partitions are reported for this small deterministic grid; it is not an
untouched final holdout. Dev-large contains the same questions.

Remaining BM25 four-turn recall weaknesses: multi-session **69.39%**, temporal
reasoning **76.01%**. Session retrieval can succeed even if head truncation removes
the answer-bearing sentence. Do not infer answer accuracy from these results.

Decision: use BM25 four turns for the first five-question live smoke test. Test
eight turns on multi-session/temporal answer failures next, subject to API batch
approval. More retrieved distractors reduce retrieval-set F1, but Reactor can cite
a subset, so final context size needs live answer and citation measurements.

The smoke plan is five history resets plus five question requests. Live execution
is blocked because `REACTOR_ACCESS_KEY` is unavailable. No live answers, answer
scores, or submission predictions have been generated. Local mocked pipeline
tests verify adapter/scorer behavior without claiming Reactor provenance.

Reports: `experiments/registry.jsonl`, initial baseline in
`experiments/20261030T212313964273Z/`, nine configurations and per-question failures
in `experiments/20261030T212244128730Z/`. The registry preserves initial runs and
subsequent comparison/provenance corrections rather than rewriting history.

Herdr caller context points to a stopped `agent-factory` session. No named session
was active, so parallel tasks used the available task-agent interface; the default
Herdr session was left untouched.
