# Independent evaluation — 2026-10-31

Base revision: `f2e124d`. Branch: `eval/independent-validity-20261031`.
All work is offline, in `/private/tmp/opentovibe-eval-validity-20261031`.
No primary-checkout edits, live Reactor requests, credential operations, external
hosted AI requests, or test-gold access were made by this workstream.

**Recommendation:** retain the user-designated **Calibrated-4 primary baseline**.
The evidence supports a retrieval improvement, not a demonstrated benchmark
answer improvement. Next live work should be only the lead's smallest approved
calibrated citation/abstention gate, after explicit **cross-machine** exclusivity,
with one runner and a 600-second timeout. Do not launch a 95-operation comparison
or the full 146-question submission. Reserve at least 2.5 hours, potentially
longer, for that final run. Local tests are not permission to advance live gates.

The organizer clarification supersedes older statements forbidding automatic
citation addition. Verified automatic attribution from **original** evidence is
permitted. Retain the Reactor-supplied citations, verified fallback citations,
and unresolved claims separately. A new automatic-policy prediction is a new
derived artifact; the original historical response/prediction stays unchanged.
Reactor must still generate the final answer. No external hosted AI API may be
part of the benchmark pipeline; deterministic/local small-model checks are valid.
Benchmark execution is within HARNESS (4 points); overall rubric is IDEA 4,
HARNESS 4, APPLICATION 4. A citation repair is not a new generated-answer result.

## Measured facts

`audit.json` independently recomputes these from local question/gold files,
recorded fit IDs, and retrieval-detail rows. It records source hashes. The
organizer scorer checkout is `f0a317dfa13e7797baae61711cef27a9805bedcc`.

* Dev: 526 questions, 496 answerable, 30 unanswerable, 470 histories (414
  single-question and 56 two-question histories).
* The fixed question-hash partition is 433 development / 93 validation.
  Recorded fitted IDs exactly match all 433 development IDs. Training used a
  grouped internal split (344 / 89) for 24 parameter trials, then refitted all
  development IDs (`experiments/calibration-r2/training.json`).
* **14 validation questions share training histories**; only 79 validation
  questions / 74 answerable have histories outside that development fit.
  That is a measured history-overlap risk. It does not prove answer-text
  leakage or quantify its effect. The 79-question remainder is also reused
  exploratory validation, not a pristine holdout.
* **Dev-large repeats all 526 IDs, question texts, answers, and evidence sets.**
  Question dates differ for 524 IDs. It tests distractor robustness, not new
  question generalization. Do not pool dev and dev-large as 1,052 independent
  observations or substitute dev dates into dev-large requests.
* 39 tracked retrieval-detail artifacts contain validation IDs. This is a
  conservative observed exposure count; it excludes other filename patterns,
  summaries and untracked runs. Repeated exposure is measured. Adaptive-selection
  bias cannot be estimated from those files alone.

Recomputed **retrieval proxy F1**, using the official session-set F1 formula on
retrieved sessions as hypothetical citations (all four match the leaderboard):

| Scope | BM25-4 | Calibrated-4 | Difference |
| --- | ---: | ---: | ---: |
| Dev, full 496 answerable (includes fit IDs) | .7647 | .8665 | +.1018 |
| Dev, reused validation 88 answerable | .7896 | .8687 | +.0791 |
| Dev, unseen-history validation 74 answerable | .7791 | .8438 | +.0647 |
| Dev-large, full 496 answerable (same questions) | .6487 | .7283 | +.0796 |
| Dev-large, reused validation 88 answerable | .6727 | .7690 | +.0963 |
| Dev-large, unseen-history validation 74 answerable | .6473 | .7253 | +.0780 |

These are **not official Reactor accuracy or actual answer citation F1**.
Equal `k=4` is not identical evidence exposure: BM25 packs four turns, calibrated
selection can pack more turns from up to four sessions. On full dev mean text
sizes are 4,078 versus 7,193 characters; dev-large 4,019 versus 7,548. A shared
12,000-character ceiling makes a policy comparison useful but does not isolate
ranking from packaging/text quantity. Record actual sizes and use a separately
declared size-matched sensitivity comparison before making a ranking-only claim.

## Recorded Reactor behavior

The two immutable historical report directories contain **one unique completed
question**, the cat-name answer `Luna`, and nine planned question exposures across
the two five-question runs remain incomplete (one completed / ten planned run
slots; duplicated questions mean this is not a unique-question completion rate).
Per-run valid-prediction completion is **1/5** and **0/5**. No live unanswerable,
temporal, update, multi-session or same-user sequence completed. No unanswered
API request should become a model error or an invented abstention.

Historical Luna local official matching: correct 1, wrong 0, unjudged 0;
**actual submitted evidence F1 0.0**. Its explanation contains `[E1]`, while its
marked final answer contains only `Luna`. The official parser correctly extracts
no final-answer citations. The current prompt's live benefit remains unmeasured.
The policy-attribution evaluation is a separate new derivative, described below.

Across the two archives there are 14 logged client invocations: five resets and
nine question invocations, plus five internal refusal retries = **19 observed
benchmark operations**. Eight question invocations failed; counting internal
retries gives 13 unsuccessful request attempts. This does not mean 13 incorrect
answers. The five safe retries were unforwarded refusals. The schema GET (404)
was a separate diagnostic request. Old checkpoints lack request IDs, so the
diagnostics conservatively flag unlogged-pending uncertainty; 19 is an observed
count, not proof of a complete lifetime ledger. Historical shared-agent
interference is a plausible cause of history changes, not established solely by
client logs.

The sole completed answer latency is 46.63 seconds (46.92 seconds including
client invocation). This selected n=1 cannot support a general latency estimate.
Organizer operational guidance is approximately 50–60 seconds for an answer
plus 15–30 seconds for a pending cycle; use 5–10-second backoff and **600-second
timeouts**. A timeout may leave processing active: wait/recover on the **same
Reactor history** after the prior request clears; **never reset on timeout**.

`historical-smoke.json` and `historical-reliability.json` are independent rescoring
reports; the original archives remain unchanged. They retain missing counts,
unjudged counts, completed-only scores, full-scope official submission penalties,
operation/retry/failure counts, latency, pending uncertainty and isolation issues.
Original older archives omitted evidence; citation validation is explicitly
unknown when original evidence is absent, rather than reporting zero invalidity
as proof. Use the original `runs/` directory for a complete new archive.

## Attribution evaluation

`evaluate_attribution.py` loads the exact separately owned `attribution.py` file
and calls `attribute_answer(question, history, evidence, result)` with **no gold**.
Only real saved completed Reactor answers enter the evaluation. The official
adapter must reproduce each original prediction. Historical versus new-policy
predictions and scores are reported separately; the answer and abstention cannot
be changed by the evaluation script. Supplied/fallback/final session IDs must be
within the original evidence and matching user history. The evaluator independently
checks support offsets, exact spans, source IDs, same-role original history turns
and presence of a verification rule for every fallback source. Semantic attribution
remains the separately versioned policy's responsibility. Full policy supports and
unresolved claims are retained. Gold is consulted only afterwards for scoring.

The primary denominator is available **real** Reactor outputs, displayed together
with public-dev coverage (526 questions / 496 answerable). The available sample
is only n=1; a repaired Luna citation cannot establish broad fallback precision,
recall, generated-answer quality, or final benchmark improvement. Full-dev
submission scoring includes missing outputs as penalties and is labeled
separately. No gold-answer oracle experiment is included in this workstream.

The actual original-BM25 Luna replay is complete: official available-output F1
stays **0.0** for the unchanged historical prediction and becomes **1.0** for the
separate automatic-policy derivative, with 0 supplied / 1 verified fallback / 0
unresolved outputs. Coverage is **1/526** dev questions. The original user span
`my cat's name is Luna` at [18:39] verifies `s_8a377a1e6a80` without gold.
See [ACTUAL_ATTRIBUTION.md](ACTUAL_ATTRIBUTION.md) and the machine-readable report.
This is a measured one-answer citation repair, not evidence of Calibrated-4
generalization or new generated-answer quality.

## Independent Gate 1–4 proposal (not an execution driver)

The lead owns the **23-operation `gate_plan`** and all integration. The following
is an independent minimal experimental-design proposal, not a competing live
plan. `evaluation_gates.py` only freezes samples, budgets and payloads; it has no
execution path and produces no live commands. Generated sources preserve original
question records/dates, current evidence, and hashes. All newly selected histories
exclude every fixed validation question and the known diagnostic histories, but
still come from fitted/explored development data. They are diagnostic samples.

| Gate | Hypothesis and frozen sample | Initial operations | Expected insight / success criterion | Stop condition |
| --- | --- | ---: | --- | --- |
| 1 | Calibrated-4 can complete a cited answer and genuinely abstain. Known cat + known unanswerable, fresh history each. | 2 resets + 2 questions = **4** | Two durable responses; correct local answer / abstention; effective citation F1 1 for the cat through supplied citation **or independently verified fallback**, with raw and effective provenance/scores distinct. No unresolved factual claim in the cat answer. | Any history mismatch, uncertain pending request, invalid or unverified fallback, wrong/undecided answer or false answer on unanswerable. Diagnose offline; no retry-until-pass. |
| 2 — A | Calibrated-4 versus BM25-4 on identical six questions, one per category plus unanswerable, six histories. Calibrated is the primary reference. | 12 resets + 12 questions = **24** | Twelve valid responses, identical attribution policy; no abstention/reliability regression. Report answer transitions after independent review of unjudged outputs, and supplied/effective F1 separately. A descriptive calibrated citation advantage with no answer loss supports retaining it; a tie supplies no new improvement evidence. | Any isolation/attribution failure, missing arm or answer-quality regression; no retuning on these outcomes. Differences in evidence text quantity prevent a ranking-only conclusion. |
| 3 — B | Same Calibrated evidence/prompt/attribution with versus without bounded **first-question-only** preload; two natural two-question histories. | 4 resets + 8 questions + 2 preloads = **14** | Four complete paired questions, no label carryover, source-grounded provenance; report first versus second question separately. A second-question benefit without first-question/answer/abstention harm justifies a new confirmation proposal, not a general memory claim. | Any contaminated prefix/future-question selection, unsupported fallback, incomplete pair, or no attributable second-question benefit. The two histories are assistant-only and cannot represent all task types. |
| 4 | Freeze one candidate before selecting eight different questions/histories, covering six strata, versus Calibrated-4. | 16 resets + 16 questions = **32**; add **8** single-part preloads if memory is the candidate | Confirm direction on new diagnostic IDs with complete output, independently resolved answer judgements, citation benefit, no abstention/reliability loss, and acceptable measured latency/cost. Require at least two net independently judged answer wins and no negative mean effective F1 before proposing larger work; citation-only gains must be labeled as such. | Any integrity failure, incomplete/unjudged comparison, no practical gain, or insufficient final execution window. Eight reused-development questions do not establish statistical generalization; never auto-launch a larger run. |

Actual offline preparation gives **74 initial operations**, or **82** with a
memory candidate at Gate 4. These exclude retries, recovery, optional controls,
and all final-submission operations. They are separate conditional budgets, not
an approved batch. If every gate were considered, 38 question requests plus
preloads could consume substantial time; protecting the final window takes
priority over exhausting an experimental budget.

Useful conditional controls, each requiring a new reviewed proposal/approval:

* Same-user sequential control: cold-start only the second question of each
  Gate-3 user under both arms, retaining the **same q1-only preload** for the
  memory arm. Four resets + four questions + two preloads = **10** extra
  operations. This separates benefit of the extra preload from ordinary q1
  evidence/answer carryover already present in both sequential arms. Without it,
  label Gate 3 a sequential integration diagnostic, not a pure memory mechanism.
* C — citation prompts: the single historical lost-final-citation case supports
  a targeted format check, not a prompt sweep. Only if a correctly completed
  Gate-1 answer still loses attribution, propose the original organizer prompt
  versus current wrapper on cat, a frozen multi-session question and unanswerable:
  six resets + six questions = **12** operations. Freeze both client hashes and
  identical evidence/attribution logic; compare raw supplied citation F1 as well
  as effective F1 so permitted fallback cannot mask a prompt effect. This is a
  replacement diagnostic after stopping, not automatic expansion of a failed gate.

Strict controls for every paired experiment:

1. Same IDs, exact question text/date, user history, scoring code, final-answer
   conversion and attribution version. Freeze evidence budget at 12,000 text
   characters; preload budget at 6,000 serialized characters, logging actual
   evidence/preload/response sizes. B uses byte-identical current-question
   evidence. Adding memory intentionally adds exposure/cost; do not call it
   equal total context. Explicitly describe A's packaging difference.
2. Fresh independent Reactor history/output/checkpoint per user and arm. Within
   a user's sequence preserve original order and **do not reset between questions**.
   Alternate arm order by user. Never reuse a timed-out or foreign history for
   the other arm. Compare local reset lineage, but do not treat that as proof of
   cross-machine exclusivity.
3. Prefix memory uses only q1 public text and original sources. The old
   `reactor_memory.prepare_memory(history, all_questions)` pools future queries;
   it is a query-aware/transductive pilot and is not a substitute for the frozen
   prefix preload. No gold, future-question evidence or prior-arm response enters
   the memory constructor. Runtime support for exact prefix payloads must be
   reviewed by its owner before live use.
4. Same official scorer and genuine Reactor answers. Keep API failure separate
   from model wrongness, all unjudged answers visible, all raw attempts/results/
   evidence/preloads and automatic attribution provenance. No cherry-picked
   repeats, manual citation edits or oracle answers in actual-output metrics.
5. No external hosted AI judge/retriever/attributor. Human adjudication or local
   diagnostics must be separately attributed; do not call them the official
   Reactor LLM judge. No live gate without explicit cross-machine exclusivity
   and one approved runner. Tests and previous gate success never authorize it.

## Reproduction

Use the existing pinned official checkout and public dev/dev-large data. In an
isolated worktree they may be read-only symlinks to an existing installation;
do not download or run bootstrap merely to perform this offline evaluation.
All output locations below must be fresh.

```sh
python3 -m unittest tests.test_evaluation_validity tests.test_attribution_evaluation -v
python3 evaluation_diagnostics.py audit --data /path/to/data/dev \
  --large /path/to/data/dev-large --out /tmp/audit-fresh.json
python3 evaluation_gates.py --data /path/to/data/dev --out /tmp/gates-fresh
python3 evaluation_diagnostics.py report --run /path/to/original/run \
  --questions /path/to/questions.jsonl --gold /path/to/gold.jsonl \
  --out /tmp/immutable-report-fresh
python3 evaluation_diagnostics.py compare \
  --arm calibrated=/tmp/calibrated/report.json --arm candidate=/tmp/candidate/report.json \
  --out /tmp/paired-fresh.json
python3 evaluate_attribution.py --run /path/to/runs/live-bm25-4-answerable \
  --questions /path/to/data/dev/questions.jsonl --gold /path/to/data/dev/gold.jsonl \
  --histories /path/to/data/dev/histories.jsonl \
  --attribution-file /exact/path/to/attribution.py --out /tmp/attribution-fresh
python3 evaluation_diagnostics.py coverage --questions /path/to/final146/questions.jsonl \
  --predictions /path/to/final146/predictions.jsonl --expected 146 \
  --out /tmp/final-coverage-fresh.json
```

The reporter preserves original raw files and evidence/preloads, hashes every
archive input and scoring implementation, and refuses overwriting. It includes
correct/wrong/unjudged counts, official completed and full-scope evidence F1,
abstention recall/false abstention, raw-response and valid-prediction completion,
invalid/unverifiable citation incidence (including rejected attempts), API
invocations/resets/retries/failures, per-operation latency, evidence content/hashes
and per-question predictions. Comparison requires identical question records and
gold and flags reused Reactor histories, missing responses, changed budgets/client
and unverified conversion. Use separate raw-policy attribution reports when
comparing derived fallback predictions. Final coverage is gold-free and shows
per-history progress; a ready coverage check is not quality evidence or launch
authorization.

Use [COMPARISON_TEMPLATE.md](COMPARISON_TEMPLATE.md) for every new result. Tiny
gates are diagnostic, not statistically powered. If a later independent cohort
is approved, freeze the candidate first, cluster uncertainty by user history,
report all repeated-selection limitations, and assess official answer quality
and effective citation F1 jointly. A favorable retrieval proxy alone is insufficient.
