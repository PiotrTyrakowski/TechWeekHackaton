# OpenToVibe — RxAI memory challenge

Benchmark-first Python retrieval and sequential Reactor execution. Final answers
are produced only by the organizer's Reactor client. No external model calls.

## Setup

Python 3.11+; run from this directory:

```sh
python3 bootstrap.py --split dev
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python prepare_smoke.py
```

`bootstrap.py` pins official tooling to commit
`f0a317dfa13e7797baae61711cef27a9805bedcc` and verifies release SHA256.
Use `--split dev-large` for scale checks (744 MB compressed); it shares dev
questions and is not an independent holdout. `--split test` fetches public test
inputs only. Data and official tooling are downloaded, not committed.

## Offline experiments

```sh
.venv/bin/python evaluate.py --data data/dev --method official --method bm25 --method bm25-context --k 4 --k 8 --k 12
.venv/bin/python -m unittest discover -s tests -v
```

Each experiment writes an append-only `experiments/registry.jsonl`, configuration,
source checksums, per-question failures, category results, and fixed hash-based
80/20 development/validation results. Gold is used only for evaluation and the
development smoke diagnostic, never by retrieval or runtime. All configurations
have the same 12,000-character passage budget. `k` is turns for `official` and
`bm25`, distinct sessions for `bm25-context`. Recall, precision, and F1 deduplicate
session IDs. Retrieval F1 treats all retrieved sessions as citations; actual
Reactor citation F1 must be measured separately. Gold evidence retrieval does not
establish that an excerpt contains the answer.

## Offline parallel research results

The completed research sprint is summarized in [reports/OFFLINE_SPRINT.md](reports/OFFLINE_SPRINT.md).
BM25 remains the simple default recommendation. `adaptive` is an experimental
broader session pool; `dense` and `dense-hybrid` are optional local MiniLM rerankers
over a BM25 top-16-turn shortlist. Dense fusion improves the retrieval F1 proxy,
but answer quality and actual Reactor citation F1 remain untested. The generic
reranker was rejected and archived under `experiments/rerank-offline/`.

Optional local embedding setup (Python 3.12; no paid inference service):

```sh
uv venv --python 3.12 .venv-dense
uv pip install --python .venv-dense/bin/python -r requirements.txt -r requirements-dense.txt
.venv-dense/bin/python experiments/dense-fetch-model.py
DENSE_THREADS=4 DENSE_CANDIDATE_LIMIT=16 .venv-dense/bin/python evaluate.py --data data/dev --method dense-hybrid --k 4
```

Model weights are pinned and kept local. Retrieval does not download them
automatically. `DENSE_MODEL_DIR` can point to an existing asset directory.
Standard-library retrieval and tests require none of the optional ML packages.
`evaluate.py --retriever-module <module>` evaluates isolated candidates without
changing the runtime implementation. Exact comparison artifacts can be collated
without repeating inference:

```sh
.venv/bin/python experiments/offline-sprint/compare.py
```

**All Reactor operations remain paused until exclusive team access is explicitly
coordinated.** The earlier history invalidations likely came from simultaneous
use of the shared agent by a teammate.

The Reactor audit and engineering work is described in
[REACTOR_DEEP_DIVE.md](reports/REACTOR_DEEP_DIVE.md),
[REACTOR_STRATEGIES.md](reports/REACTOR_STRATEGIES.md),
[REACTOR_RELIABILITY.md](reports/REACTOR_RELIABILITY.md), and
[REACTOR_EVALUATION.md](reports/REACTOR_EVALUATION.md).
The default is evidence-first RAG with persistent per-user conversation state.
An optional bounded preload pilot uses Reactor's documented memory ingestion;
neither memory benefit nor improved citation quality has yet been established live.

Round two adds a frozen, supervised session selector (`--method calibrated`) with
standard-library inference. Its weights were fitted only on the 433 development
question IDs; validation and dev-large scale results are kept separate in
[reports/MAXIMUM_SCORE_R2.md](reports/MAXIMUM_SCORE_R2.md). Full-dev fitted metrics
are not held-out answer accuracy. The fact-memory, complementary, and mixed-scale
refit experiments did not justify promotion; their code/reports remain reproducible.

```sh
.venv/bin/python evaluate.py --data data/dev --method calibrated --k 4
.venv/bin/python bootstrap.py --split dev-large
.venv/bin/python evaluate.py --data data/dev-large --method calibrated --k 4
.venv/bin/python experiments/maximum-score-r2/summarize.py
```

No model training is needed for inference: `models/session_selection.json` is a
small frozen artifact. `train_session_selection.py` reproduces development-only
fitting using NumPy (available in the optional Python 3.12 environment).
`--retriever-file path/to/candidate.py` evaluates an exact isolated source file,
avoiding similarly named modules in another worktree.

## Five-question Reactor smoke test

Configure `REACTOR_ACCESS_KEY` privately in the invoking process environment.
Never put its value in commands, source files, logs, or chat. The runner reports
only whether it is available. The supplied team URL/agent are the CLI defaults.

```sh
.venv/bin/python runtime.py --questions smoke/questions.jsonl --histories data/dev/histories.jsonl --out-dir runs/smoke-bm25-k4 --method bm25 --k 4 --limit 0
```

This dry run prepares evidence and reports the call plan. Five selected questions
use five histories: **5 history resets + 5 question requests**, before the official
client's safe retries of refused, unforwarded messages. To execute the authorized
small smoke test, coordinate exclusive access, record its named participants and
start/end times using the [access-window schema](reports/REACTOR_RELIABILITY.md),
and repeat that command with
`--execute --exclusive-access --access-window runs/agreed-window.json`. The manifest locks data,
question selection, client version, retrieval configuration, and evidence.

```sh
.venv/bin/python evaluate.py --data data/dev --questions smoke/questions.jsonl --predictions runs/smoke-bm25-k4/predictions.jsonl
.venv/bin/python official/score.py smoke/gold.jsonl runs/smoke-bm25-k4/predictions.jsonl --details runs/smoke-bm25-k4/score-details.jsonl
```

The five-question smoke sample includes an unanswerable case and user, assistant,
multi-session, and update questions. It is an integration diagnostic, not a model
selection sample. Temporal reasoning is covered in full offline evaluation.

## Execution and recovery

`runtime.py` groups questions by dataset history, creates one Reactor history per
group, asks sequentially, and preserves history-local session dates and question
dates. It validates the final formatted message against 16,000 characters before
sending. Evidence uses session IDs and keeps both speaker roles.

Each output directory holds `plan.json`, evidence, durable `checkpoint.json`,
raw `attempts.jsonl`, successful official `results.jsonl`, and generated
`predictions.jsonl`. Repeating the same command resumes completed questions and
the active Reactor history. Do not run another job against our single agent:
starting a different history invalidates the current one. Failed or uncertain
calls stop execution; timeouts are never silently converted to abstentions.
Inspect raw attempts and checkpoint before recovering an uncertain call. Preserve
the artifacts; do not manually edit answer predictions. Unexpected citations,
citations outside the corresponding history and missing/duplicate IDs are rejected.
Uncited Reactor answers are preserved with their actual zero evidence score; labels
in explanatory text are never moved into a final answer. Only actual Reactor abstentions become
submitted abstentions.

For final-line citation instructions and redacted WebSocket close diagnostics,
the runner now defaults to `reactor_client.py`. The wrapper keeps the official answer parser
and citation mapper unchanged. `--stop-after 1` pauses after one completed question
without changing the five-question manifest, allowing a citation check before
continuation. The 2026-10-30 investigation remains blocked on remote history
invalidation; see [the reliability report](reports/REACTOR_RELIABILITY.md).

Live execution requires `--exclusive-access` and a bounded `--access-window`
attestation that the team has actually coordinated access. Every operation must
fit its timeout plus a 15-second reserve inside the window. This records agreement;
it cannot independently verify another teammate is idle. The local lock is shared across worktrees and
clones belonging to this machine user, but cannot control another machine or an
uncooperative client. Dry runs never invoke Reactor. Adopting an unexpected
server-reported history is disabled because it may contain another user's memory.

`--memory-mode targeted --memory-budget 12000` opts into a query-aware shared
source ledger loaded with `--text` before answering. It pools verbatim retrieved
excerpts across that user's selected public questions, uses stable session IDs
and dates, and assigns no E labels. Each final question still supplies original
evidence for citations. This is a bounded hybrid pilot, not full native-history
ingestion. It adds at most one preload per history with the default limits;
the dry-run count is authoritative. Auxiliary loading replies never become
predictions, and uncertain loading operations stop rather than replay.

Generate the frozen offline plan (no Reactor requests), then archive and compare
actual live arms only after their acceptance gates and coordinated windows:

```sh
.venv/bin/python experimental_plan.py --out-dir runs/reactor-deep-dive-plan
.venv/bin/python smoke_report.py --run runs/arm-a --questions selected/questions.jsonl --gold selected/gold.jsonl --out reports/arm-a
.venv/bin/python compare_reactor.py --arm bm25=reports/arm-a/report.json --arm calibrated=reports/arm-b/report.json --out reports/paired.json
```

The planner produces exact per-history commands with all three arms and a rotated
arm order. It has no execution option. Its default 17-question comparison needs
95 initial operations, before retries; this is a proposal, not batch approval.
Reports distinguish incomplete requests, local unjudged answers, actual final
citations, preload cost, and latency. Completed answers with missing citations
are retained with their actual zero Evidence F1.

A successful response durably recorded in `attempts.jsonl` can be recovered after
a local validation/write failure without sending the question again. Uncertain
timeouts remain blocked. After inspecting a server `closed` response,
`--retry-closed` explicitly permits one retry in the same history. If the server
replaced a history before any question in it succeeded,
`--restart-interrupted-history` permits one logged recovery reset. Repeated
history replacement needs investigation for competing runners or server faults.

Local `score.py` automatically matches some answers; other answers remain
**unjudged**, not proven wrong or correct. Official scoring uses an LLM judge.
Evidence F1 counts on every answerable question, including abstentions.

## Test submission (requires approval before the large API batch)

```sh
python3 bootstrap.py --split test
.venv/bin/python runtime.py --questions data/test/questions.jsonl --histories data/test/histories.jsonl --out-dir runs/test-v1 --method bm25 --k 4 --limit 0
```

Choose a configuration from measured dev results before execution. The public
test description reports 146 questions across 15 histories: approximately 161
initial API operations; the actual dry run is authoritative. Review the plan,
obtain approval and exclusive access, then use
`--execute --exclusive-access --access-window runs/agreed-window.json`. Completion checks exact selected question
coverage and per-history citations. Keep the raw results, manifest, checkpoint,
code revision, and final predictions together for reproducibility.

Official sources: [rules and scoring](https://github.com/RxAI-dev/memory-challenge),
[participant kit](https://github.com/RxAI-dev/memory-challenge/tree/main/reactor),
[data release](https://github.com/RxAI-dev/memory-challenge/releases/tag/data-v1).
