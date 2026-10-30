# Reactor evaluation: gated, reproducible live experiments

Status: **offline infrastructure validated; live experiments await an actual team
exclusive-access agreement.** No new model answers or judging points are claimed.
The three highest-value experiments are final-answer citation correctness,
paired retrieval through Reactor, and bounded shared-context memory versus the
same retrieval without a preload. Full-history ingestion and extra reasoning
turns follow only if these smaller experiments justify their cost.

## Reproduce the offline plan

```sh
.venv/bin/python experimental_plan.py --out-dir runs/reactor-experiment-plan-v1
.venv/bin/python -m unittest tests.test_experimental_plan -v
```

The planner calls **only `runtime.prepare`**, which retrieves and packages local
data. It never invokes `runtime.run`, the client, a history reset, or a network
operation. It has no `--execute` option. Generated runtime commands also default
to dry runs. Five tests validate deterministic sampling, development-only history
selection, exact counts from prepared memory parts, separate arm output
directories, all six arm orders, refusal to overwrite any existing artifacts,
and rejection of `--execute` by the planner. Always choose a new plan directory.

The final audited local plan is `runs/reactor-experiment-plan-final/plan.json`.
Its compact tracked [validation record](reactor-deep-dive/offline-validation.json)
records 99 integrated tests, source hashes, exact selection and limits. A full
local simulation exercises the actual runner, official parser, prediction
adapter, and scorer with only network transports replaced. These are plumbing
checks, not Reactor benchmark results.

The generated directory contains:

- `plan.json`: frozen question IDs, per-history arm order, call counts, source
  hashes, selection limitations, and commands as argv and shell text.
- `commands.md`: individually reviewable **dry-run** commands in stage order.
- `inputs/histories.jsonl`: original public history lines, unchanged, restricted
  to selected histories; this avoids repeatedly scanning the full dev corpus.
- Per-job question files, evaluation-only gold files, and exact manifests from
  `runtime.prepare`, including evidence hashes, actual message sizes, and preload
  text hashes. Gold is never passed into the runtime or memory constructor.

Source hashes include original input files, the planner, evaluation split helper,
reporter, and all runtime-manifest sources. Regenerate the plan after source or
configuration changes; preserve the original plan when reporting a completed run.
No command in the generated plan automatically executes the next stage.

## Exact initial API budget

These are **fresh-run initial operations** from the actual local preparation with
12,000-character evidence and memory budgets. Safe unforwarded-refusal retries,
failed calls, and recovery add operations and must be logged separately.

| Stage | Unique questions per configuration | Configurations | History resets | Question requests | Preload requests | Initial operations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1: Citation gate | 1 | 1 | 1 | 1 | 0 | 2 |
| 2: Diverse smoke | 5 | 1 | 5 | 5 | 0 | 10 |
| 3: Paired comparison | 17 | 3 | 33 | 51 | 11 | 95 |
| All proposed stages | diagnostic overlap retained | — | 39 | 57 | 11 | 107 |

The preload arm prepares one part for each of the 11 histories in this plan.
Changed budgets/data may change that number; the regenerated manifest is
authoritative. A text acknowledgement is a real agent turn, not a free upload.

For scheduling only: the sole prior completed question took 46.63 seconds.
At that rate 57 question turns take approximately 44 minutes; preload turns,
history creation, retries, and human review add time. This is **not** a latency
estimate supported by a representative sample. Measure all stage-1/2 timings
before agreeing a larger access window. The official 300-second timeout includes
safe internal retries; our runner reserves another 15 seconds per subprocess
before starting it inside an agreed window.

## Stage 1: answer and citation gate

Use `q_d4ead82e5cad`, the already diagnosed cat-name question, with BM25-4 and the
new outbound prompt. This is a regression diagnostic, not new performance data.
Use a new output directory and create a history only after confirming that no
other teammate owns the shared agent. Never resume the old invalidated history.

Acceptance requires all of the following:

1. One successful reset and one completed question with no foreign-history
   adoption, uncertain pending operation, or unexplained transport failure.
2. Correct matching ack/current-ref handling and an actual marked answer from
   Reactor. Keep its raw reply and extracted answer.
3. Correct answer and the actual supporting `[E#]` in the marked segment. Mapping
   must yield the correct session. A narrative-only citation fails this gate.
4. Runtime validation and official prediction conversion accept the output;
   official local scoring reports a correct answer and Evidence F1 1.0.

Do not add citations after the call, edit predictions, or retry repeatedly until
one good output can be selected. A failure is recorded and diagnosed. A planned
new prompt trial is a separate run with an explicit changed configuration.

## Stage 2: diverse five-question smoke

Use the existing `smoke/questions.jsonl` selection without choosing replacements
based on retrieval success. It includes user fact, assistant fact, multi-session,
knowledge update, and unanswerable cases. It does **not** include a temporal
question; Stage 3 adds one. These questions have prior diagnostic exposure, and
their results must remain labeled as such.

| Question | Check |
| --- | --- |
| `q_d4ead82e5cad` | User fact; final-segment citation |
| `q_e2cc79359e15` | Assistant fact and completeness of the requested list |
| `q_6eaf85dde884` | Multi-session combination and all necessary sources |
| `q_61a19ce280f4` | Updates/comparison, avoiding wrong-person inference |
| `q_1773242b1801` | Unanswerable near miss; genuine marked abstention |

Report every question, failure, pending request, prediction, and unjudged answer.
If citation mapping, isolation, or transport correctness fails, stop expansion.
An ordinary wrong model answer remains a measured answer failure, not a reason
to remove that question. Proceed only when the runner's operation is understood
and correct enough to make a paired comparison interpretable.

## Stage 3: paired retrieval and memory comparison

The arms use the same prompt, evidence budget, question order within a user,
client, and dates:

| Arm | Retrieval | Preload | Initial operations |
| --- | --- | --- | ---: |
| `bm25-4` | BM25, four turns | None | 28 |
| `calibrated-4` | Frozen calibrated selector, k=4 | None | 28 |
| `calibrated-memory` | Same frozen calibrated selector and evidence | Bounded source ledger | 39 |

The memory comparison isolates **adding a preload**, because its final-question
retrieval is identical to `calibrated-4`. The preload pools verbatim, source-linked
excerpts selected across the public questions of that user, keeps their local
dates and roles, and loads them before answering. It contains no gold answers,
generated conclusions, or invented structured facts. It is a targeted hybrid
memory pilot; success would not prove unaided native retrieval from full history.

The frozen sample has two separately reported cohorts:

- **Shared-memory diagnostic:** 12 questions from six natural two-question
  histories. Six histories receive all six permutations of arm order. Within a
  history every selected question keeps its original order, without a reset
  between them. This tests context accumulation and current-question label
  remapping. These natural pairs are all assistant-fact questions, which limits
  generalization.
- **Representative category coverage:** five previously unselected singleton
  histories, one each for user fact, multi-session, knowledge update, temporal
  reasoning, and unanswerable. These extend coverage but one example per stratum
  cannot establish reliable category accuracy. Singletons test preload context,
  not cross-question accumulation.

In the local inputs, 526 dev questions map to 470 distinct history IDs: 56
two-question histories and 414 singletons. Selection hashes `reactor-memory-v1`
with public IDs, excludes every history containing a Stage-1/2 diagnostic or a
fixed validation-partition question, and uses gold only to stratify the five
singletons. The calibrated weights already fit development data. Consequently,
this experiment measures integration behavior on development examples; it is
not a clean estimate of calibrated-model generalization. Existing offline
validation results remain separate and must not be repeatedly retuned.

Execute jobs in the exact generated schedule: one history and one arm per job,
every job with a unique output/checkpoint directory. Each arm starts its own
fresh Reactor history. Finish all questions of that user before the next arm's
reset. An arm cannot reuse the previous arm's Reactor state or checkpoint.
Counterbalancing reduces order/time drift; it does not eliminate stochastic
variation or shared-provider effects. Do not mix arms concurrently on our agent.

## Metrics and reporting

Use each generated `report_command` after a run is settled. It invokes the
existing `smoke_report.py`, which snapshots raw attempts, results, checkpoint,
plan, and predictions and computes official local score functions without
rewriting predictions.

Report the following for every question, each arm, each cohort, and category:

| Measure | Definition |
| --- | --- |
| Completion | Completed valid predictions / planned questions; incomplete and pending shown separately |
| Answer correctness | Correct, wrong, and **unjudged** local outcomes; unmatched text is not automatically wrong |
| Evidence F1 | Official per-question F1 of submitted session IDs against gold, averaged over **all answerable questions**, including false abstentions |
| Citation precision/recall | Session-set overlap of actual final-segment mapped citations; show these alongside F1 |
| Final citation coverage | Non-abstained answerable completed answers with a valid current final-segment citation / such answers |
| Invalid citation rate | Unknown labels, unmappable IDs, or metadata mismatch failures / attempted questions |
| Abstention | Unanswerable abstention recall, answerable false-abstention rate, and genuine abstentions versus transport failures |
| Calls | Reset/preload/question invocations, reported internal safe retries, recovery operations, and all known unlogged in-flight uncertainty |
| Latency | Question and preload durations, per-question total attempt time, median/p95 when meaningful, end-to-end elapsed time |
| Reliability | Transport and lifecycle failure rates by code; pending/uncertain operations; crash recovery success |

`smoke_report.py` provides completion, per-question final citations, citation
coverage, Evidence F1/precision/recall, correctness/unjudged status, abstention,
preload/question/reset calls, retries, latency p50/p95, failed-invocation rate,
and archived access-window records. The generated plan's `compare_command` uses
`compare_reactor.py` to combine all disjoint per-history archives for each arm,
require identical combined question IDs, and report paired F1 deltas and every
incomplete pair. Its reference arm is BM25-4. The script compares reports without
concatenating or editing predictions, rejects overlapping per-arm question IDs,
and hashes every input report. Run each job's `report_command` first, then use:

```sh
# Obtain the exact comparison command from the frozen plan or commands.md.
.venv/bin/python -c 'import json; print(json.load(open("runs/reactor-experiment-plan-v1/plan.json"))["compare_command"])'
```

Do not treat unrun comparison commands as new live measurements. Full final-submission
coverage must still be checked, since the official scorer counts missing
questions as wrong. Diagnostic completed-only statistics never hide missing IDs.

Compare per-question paired outcomes, not differently selected arm averages.
Report shared-history first-question versus second-question outcomes to expose
memory benefit or contamination. Aggregate the six shared histories separately
from the five category singletons; an aggregate dominated by assistant questions
must not be sold as representative accuracy. Include all failures and avoid
choosing winners from one additional correct answer in a 17-question pilot.

## Stage 4: larger evaluation proposal, after the gates

After Stage 3, freeze one candidate and its prompt before selecting a new cohort.
A useful bounded next proposal is 30 new development questions in 30 distinct
histories, selected without answer/retrieval-based filtering, compared against
BM25-4. With two evidence-only arms that is **60 resets + 60 questions = 120**
initial operations; if the winner has exactly one preload per history, add 30
preloads for **150**. The new dry run must confirm those assumptions and produce
the actual counts before live approval and access scheduling. A larger held-out
evaluation can follow without further tuning on those held-out answers.

This is a proposal, not authorization to launch a batch. Promotion should require
joint evidence of answer quality, actual citation F1, abstention, reliability,
and a latency/call cost that fits the remaining test window. A reliable baseline
beats an unvalidated memory demonstration for submission; a validated memory
benefit would additionally support the IDEA and HARNESS presentation with a
specific controlled result. Application/business opportunities are documented
elsewhere; no frontend is built in this workstream.
