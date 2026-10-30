# Maximum-score audit and optimization round two

Historical measurement report. Organizer clarifications now permit verified
automatic citation attribution and forbid hosted auxiliary AI benchmark
processing; current integration/tests/decisions are in
[PROJECT_STATUS.md](PROJECT_STATUS.md). Raw historical predictions below remain
unchanged; new policy-derived attribution is reported separately.

## Honest live status

One unique Reactor question has completed: cat name `Luna`, exactly matching gold.
Local official scoring marks that one answer correct, with zero unjudged answers
and **official evidence F1 0.000**. The final answer omitted citation labels,
although the explanation cited the right passage. No nonempty final-answer
citation has yet been validated live. This is not evidence of general answer
accuracy, and the official answer LLM judge has not been run.

No unanswerable question has been tested live. No live multi-session, temporal,
or update answer completed. The revised citation prompt, same-history question
sequences, abstention behavior, interrupted API recovery, and large test-run
reliability remain live-unverified. Offline/mocked tests do not close those gaps.

Lifetime recorded benchmark operations remain **19: five successful resets and
14 question request attempts**. One produced an answer; 13 did not: four closed,
four history-changed, five previous-pending. Five were safe internal refusal
retries, not forwarded model questions. A separate unauthenticated schema GET
returned 404. Team-reported concurrent use of the shared agent is the likely
session invalidation cause. **Round two made zero Reactor calls**, and no final
predictions or citations were manually edited.

## Dataset audit and actual measurements

Dev has 526 questions, 496 answerable and 30 unanswerable, across 470 distinct
referenced histories. Existing exploratory partition: 433 development and
93 validation questions (408/88 answerable). Fourteen validation questions share
histories with development; 79 questions, including 74 answerable, have entirely
unseen histories. All reported evidence metrics exclude unanswerable questions;
latency/size include the whole selected scope.

Dev-large was downloaded from the official pinned release and verified against
SHA256 `9c828cefe481df9ede15089caccc6fb725909ce671ca499c7a2230556956de51`.
It contains the **same 526 question IDs and text**, with identical answers,
abstention labels, and evidence sets. Evidence list order differs for 114 rows,
and question timestamps differ for 524. Its 2.45 GB histories therefore test
distractor scale, not independent generalization. Every run used split-local
question and session dates. Public test data has not been evaluated; no test gold
has been accessed.

### Held-out question subset: 93 questions / 88 answerable

| Dataset | Method | Recall | Precision | Retrieval F1 | All gold sessions |
|---|---|---:|---:|---:|---:|
| dev | BM25-4 | 84.64% | 78.88% | 78.96% | 70.45% |
| dev | dense fusion-4 | 88.14% | 88.07% | 85.24% | 76.14% |
| dev | calibrated-4 | **90.47%** | 86.65% | **86.87%** | **82.95%** |
| dev-large | BM25-4 | 75.57% | 65.81% | 67.27% | 63.64% |
| dev-large | dense fusion-4 | 79.51% | 68.37% | 70.59% | 68.18% |
| dev-large | calibrated-4 | **83.62%** | **75.28%** | **76.90%** | **73.86%** |

This is reused exploratory validation, not a pristine final holdout. On dev the
calibrated-minus-dense F1 difference is +1.63 points, paired bootstrap95%
[-1.78,+5.07]. On entirely unseen dev histories they are essentially tied:
84.38% versus 84.47%. On dev-large the full validation difference is +6.31 points,
exploratory interval [+1.61,+10.98], but the unseen-history-only difference is
+3.77 points, interval [-0.95,+8.25]. These question-level intervals do not correct
for history clustering or repeated experimentation.

### Full 526-question measurements

| Dataset | Method | Recall | Precision | Retrieval F1 | All gold sessions |
|---|---|---:|---:|---:|---:|
| dev | BM25-4 | 84.88% | 75.52% | 76.47% | 73.79% |
| dev | dense fusion-4 | 85.73% | 82.36% | 80.77% | 73.39% |
| dev | calibrated-4 | 89.86% | 86.74% | 86.65% | 81.45% |
| dev-large | BM25-4 | 77.48% | 61.26% | 64.87% | 65.12% |
| dev-large | BM25-8 | 84.92% | 41.25% | 51.77% | 75.60% |
| dev-large | calibrated-4 | 82.53% | 69.74% | 72.83% | 72.78% |

The calibrated model fitted the 433 development question IDs. Full-dev numbers
include fitted examples, and dev-large repeats those questions with more
distractors. They must not be advertised as independently held-out answer results.
Dense fusion has only a 93-question dev-large measurement, not a full526 result.

The previous highest measured recall remains adaptive-8 on full dev: 97.60%,
precision 14.74%, F1 24.85%, all-gold 95.36%. This illustrates why high recall alone
is not close to100% competition performance.

## What changed and what failed

Three isolated research agents ran structured memory, complementary reasoning,
and supervised session calibration. No running named Herdr session existed; task
agents used independent worktrees without launching panes in default.

**Successful candidate:** frozen standard-library logistic session selection over
BM25 top 64 turns. Thirty query/candidate features feed a 3.6 KB artifact; a
development-calibrated expected-F1 surrogate selects up to four sessions. Gold is
used only in training and evaluation, never at inference. IDs are not model
features. Training choices used a history-grouped internal holdout, then one
frozen validation run. The original artifact hash remains
`a6ad9390c75b8703641995125ccc7b1226811ab9a53447d73576f274c72dd718`.

It improves dev-large F1 by 7.96 points over BM25-4, with mean 311 ms retrieval
versus329 ms in the two-config baseline run. The full calibrated dev-large run
took 176 seconds; two BM25 configurations took 359 seconds. Dense validation
averaged 889 ms per question and 96 seconds total, including local embeddings.
These are measured local wall times, not Reactor latency or monetary API costs.

**Rejected structured memory:** deterministic verbatim sentence/fact cards,
query-only calibration, and source/date provenance. Development F1 80.59% did not
generalize: validation 78.81% versus dense 85.24%. It shortened context to roughly
1,753 characters but lost useful evidence. Preprocessing 1.664M cards over 393
development histories took 44 seconds; warm cached lookup was cheap. This rejects
this particular deterministic extraction/selection design, not every possible
LLM-extracted fact database or temporal graph.

**Rejected complementary retrieval:** explicit question-clause/event anchors and
session diversity improve multi-session/temporal coverage but reduce precision.
Selected validation F1 74.09%, full-dev F1 71.88%; no runtime promotion.

**Rejected mixed-scale refit:** development-only dev/dev-large augmentation,
grouped splitting, and an extra corpus-size feature selected top32 candidates.
Validation F1 declined to 85.86% dev / 74.81% dev-large. Preserve the original
top64 selector. No further tuning followed validation; coefficients, feature
cache, all internal configurations, and negative results are recorded.

## Remaining bottlenecks and readiness

At dev-large scale the retained selector has full evidence on only 72.78% of
answerable questions. Multi-session recall is 66.01% and temporal 73.22%; these are
the main remaining recall gaps. Its four-session cap cannot fully recover 14
answerable dev questions with five or six gold sessions. That is a structural
limit, not a reason to call its 89.86% small-dev recall sufficient.

Abstention is unvalidated. The model's weak development-only absence diagnostic
does not justify an abstention override; Reactor must still determine evidence
sufficiency. Sentence context can omit answer-bearing facts even when the session
ID is correct. No current retrieval proxy measures the complete competition score.

There is **no complete citation-validated best Reactor configuration**. The
recommended next candidate is `--method calibrated --k 4` with `reactor_client.py`,
compared against dense fusion and BM25 controls after exclusive access. BM25
remains the operational retriever default; the citation-aware wrapper is now the
client default. First require one correct answer with a correct nonempty citation,
then finish the five-question smoke test, including an additional unanswerable
probe before larger batches receive approval.

Local safeguards now require `--exclusive-access` together with `--execute` and
use a machine/user-level lock shared by worktrees/clones. This does not coordinate
another machine or a teammate using a different client. No actual shared-agent
operation occurred while adding these guards. Candidate evaluation can name an
exact `--retriever-file` to avoid cross-worktree import shadowing.

Adopting an unexpected server-reported history is now explicitly disabled: it
could contain a teammate's or another dataset user's memory. Historical diagnostic
attempts remain recorded, but no completed answer came from that experiment.

The final cheap, cached cap diagnostic is also negative: increasing the original
selector's cap from 4 to 6/8 reduces in-sample development F1 (86.60% to 86.49%) and
dev-large development F1 (71.95% to 71.37%/71.29%). On dev-large, cap6 adds seven
relevant and 62 irrelevant sessions. Only one additional over-four-source case
recovers all gold. This uses fitted development examples only, with no new
training, ranking, validation, or API calls; it does not establish held-out
performance. Lifting the cap alone is not the next winning change.

Next offline work: improve relevance order and count calibration with internally
grouped evidence, retain source-level facts during packing, and measure candidate
pool ceilings before adding neural cost. Do not tune a new policy on the reused
validation table and call it an independent improvement.

## Reproduction and judging

`experiments/maximum-score-r2/summarize.py` reconstructs leaderboard metrics and
paired uncertainty from exact per-question artifacts, without model/API calls.
Full outputs contain configurations, source/data hashes, category breakdowns,
latencies, scope, and zero Reactor counts. Individual method reports document
their fixed training and validation policies.

The final local suite has **67 passing tests**. A five-question calibrated dry
run and an exact-source evaluator integration check passed without invoking
Reactor. These validate local contracts, not answer generation or live citations.

The user-provided criteria allocate IDEA 4 / HARNESS 4 / APPLICATION 4. No awarded
judging points or benchmark-to-point conversion has been verified. Reliability
guards and compact evidence selection support a harness narrative, but the live
citation gate remains unmet. Product opportunities are recorded separately in
`DEMO_OPPORTUNITIES.md`; no frontend was built.
