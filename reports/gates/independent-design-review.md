# Independent experiment review — 2026-10-31

Historical pre-clarification review. Organizer permission for verified local
citation fallback, the calibrated baseline and 600s recovery policy supersede
older assumptions below; current decisions are in [PROJECT_STATUS.md](../PROJECT_STATUS.md).

Scope: offline review of repository at f2e124d, the five requested reports, runtime.py, reactor_memory.py, retrieval_calibrated.py, smoke_report.py, compare_reactor.py, official/score.py, and relevant tests. No Reactor, web, paid-model, or credential operations. This is an acceptance/design review; no new benchmark measurement.

## Decision

Keep BM25-4 evidence-only as the operational control, citation-aware reactor_client.py as the client, and the original frozen calibrated-4 selector as the leading offline candidate. There is no citation-validated best Reactor configuration. Prioritize protocol/citation correctness before another retrieval change; do not promote calibrated retrieval or targeted preload from retrieval F1 alone. The original 95-operation combined comparison stays deferred.

Existing evidence supports only one completed real answer (Luna), locally matched correct with empty citations and evidence F1 0. The current evidence does not establish real abstention, update/temporal reasoning, same-user persistence, prompt compliance, memory gain, or any awarded judging points. The 99-test record is a prior offline result, not independently rerun by this review. MAXIMUM_SCORE_R2's 67-test statement predates the deep-dive's 99-test record; use a fresh suite count in current status rather than merging these counts.

## Smallest useful gates and acceptance

| Gate | Small experiment | Acceptance and interpretation |
|---|---|---|
| 0 | Run local protocol, guard, crash, parser, adapter, and scorer tests; rescore immutable historical answer | Current-ref/cycle filtering, final-only citations, current E-label mapping, source/history membership, genuine abstention parsing, no uncertain-call replay, and shared-access refusal work locally. Preserve historical F1=0. Mock success proves plumbing only. |
| 1 | One reset and the diagnosed cat-name question, first job in a frozen smoke plan | Actual Reactor marked final contains correct answer and supporting current E label; official conversion accepts it and local evidence F1=1. No foreign-history adoption, unresolved pending state, or unexplained failure. Incorrect or uncited completed output is retained as a failed gate, never repaired. |
| 2 | Existing five category smoke questions plus one natural same-user two-question history, preserving original question order | All planned questions and failures accounted for; genuine abstention on the known unanswerable; same server history across the natural pair with no intervening reset; second-question evidence labels mapped to its own sources. No isolation/protocol failure or unresolved request. Report model errors separately from transport failures; do not drop a question because its retrieval or answer is poor. This gives seven questions/six histories, not comprehensive category accuracy. Temporal is absent unless a predeclared additional singleton is added. |
| 3 | One preselected natural pair, BM25-4 versus frozen calibrated-4, same prompt and evidence budget | Both complete with valid comparable archives and no unresolved lifecycle issue. Report paired answer status and actual citation F1, including first/second position. A two-question pilot checks integration and gathers direction, not a statistically established winner. Prefer two pairs with reversed arm order before expansion if drift or a putative gain matters. |
| 4 | Same pair and calibrated final evidence; add bounded targeted preload in a fresh history | Final evidence and question sequence match control exactly; only preload policy changes. Account for its extra turn, context, latency, failures, and abstentions. All actual outputs retained. A difference estimates this complete preload policy, not persistence alone; matched-context follow-up is needed for a memory-mechanism claim. |

All live gates remain blocked until an explicit cross-machine exclusive agreement identifies exactly one runner. A local lock, a quiet local process list, or an invented access-window file cannot satisfy that condition. Revalidate the agreement before reset, preload, and question. An accepted request can continue remotely after a timeout; handoff must resolve that uncertainty before another runner acts.

## Calls and cost

For H distinct dataset histories, Q final questions, and P prepared preload parts:

- Evidence-only: H+Q initial operations.
- Preload: H+Q+P initial operations.
- Two fresh evidence-only arms: 2(H+Q).
- Fresh evidence-only versus preload: 2(H+Q)+P.
- Reusing an eligible frozen evidence-only control: only H+Q+P new operations.

Gate0 requires zero Reactor operations. Gate1 costs 2. Gate2's seven-question/six-history plan costs 13 total; if Gate1 is already completed within the exact same frozen smoke protocol it costs 11 additional, not 13 additional. A one-history/two-question Gate3 costs 6 fresh operations. Gate4 costs 7 for both fresh arms when P=1, or 4 additional with an eligible control. This yields 23 initial operations through all gates under fresh Gate3 and reused Gate4 control; it is a sequence of individually reviewed gates, not authorization to run 23 operations. If Gate3's BM25 pair is predeclared for exact Gate2 reuse, another 3 operations may be saved, subject to artifact and sequence requirements below. Adding a temporal singleton to Gate2 adds 2.

Safe refused retries, failures, recovery, ambiguous in-flight requests, and any repeated planned run add operations. Count them separately. Dollar pricing is absent from the inspected kit; monetary estimates are unknown. Time is H*t_reset + P*t_preload + Q*t_question + retries/wait/recovery. The sole 46.63s completion is an anecdote, not a representative estimate; use fresh Gate1/2 timings before scheduling larger work. Each operation needs the client's timeout plus 15s reserve within its real access window.

## Reuse and experimental integrity

An evidence-only control may be reused as an immutable measurement, never as live server state, only if reuse is predeclared, the arm started in a fresh history, every question in that user's selected sequence is complete in exactly the same order, and prompt/client/official parser/retrieval/model/data/question/date/budget/final-evidence hashes match the intended control. Reject unresolved pending/recovery ambiguity or contamination. Preserve full source manifests, question sequence and attempts; never hand-edit predictions or carve out only favorable questions. Gate4 gets a fresh Reactor history. A time gap and fixed control-first order remain confounders even with exact hashes.

The calibrated selector fitted development questions; neither these pilots nor dev-large (same questions with more distractors) establish held-out generalization. Gold may stratify categories/abstention and evaluate outputs, but never select successful examples, choose evidence, generate memory, infer runtime abstention, or alter predictions. Repeated tuning on the reused 93-question validation subset is exploratory. Full future public questions influence targeted memory preparation; disclose that lookahead.

## Metrics and code risks

Show planned/completed/missing/pending counts first. For completed outputs, report local correct/wrong/unjudged counts; unjudged is not automatically wrong or correct and the official LLM judge has not run. Citation F1 is macro per-answerable-question over actual submitted session IDs, including false abstentions. Show abstention recall on gold-unanswerable questions and false-abstention rate on gold-answerable questions, with denominators. Final-citation coverage excludes abstained answers, so it cannot replace F1. Separate completed-only diagnostics from final-submission full-scope scores. Incomplete runs cannot establish an overall winner; official final scoring counts missing answers as wrong.

Concrete risks from current code:

1. compare_reactor.compare verifies qID scopes and gold consistency, but not client/prompt/retrieval/data/evidence hashes, user sequence, or history isolation. Human review of frozen runtime manifests remains necessary before accepting a causal comparison. Comparing archives alone is insufficient.
2. smoke_report and compare_reactor intentionally publish completed-only metrics; omitting their scope/missing fields can manufacture a good-looking performance claim. Citation-coverage denominator excludes false abstentions. Preserve both diagnostics and full scope.
3. tests/test_reactor_end_to_end.py's same-user q1/q2 both use s_cat. It tests sequencing but not E1 remapping to a different second-question source. A distinct-source local fixture and actual second-question source inspection strengthen Gate0/2.
4. reactor_memory.prepare_memory pools retrieved excerpts for all public questions and hardcodes 12000 as its retrieval budget. Freeze the evidence budget at 12000 for this first comparison; otherwise final-context versus preload differences require separate accounting. Extra context and an extra turn confound a pure persistence claim.
5. Calibrated packing takes only two highest-ranked turns plus neighbors and truncates under a per-session cap. A correct selected session does not guarantee that the answer-bearing clause survives. Memory then preserves these already truncated excerpts, so verbatim memory is not full-source coverage.
6. Shared-access checks are operator attestation plus a local advisory lock, not a distributed lease. Direct clients and another machine can still invalidate a history. Expiry prevents new work but cannot cancel accepted remote work.

## Ranked next offline work

1. Finish Gate0 and freeze the tiny gate plan, exact evidence, provenance, counts, and failure handling. Highest immediate value: make the first real answer informative instead of spending calls on unresolved protocol behavior. API cost zero.
2. Audit packed answer-span retention on internal development groups. Separate candidate-pool absence, session-selection miss, and packing loss; annotate a small fixed sample against original source text, retaining assistant facts, updates and negation. Gold is evaluation only. Answer-string retention is a lower-quality diagnostic for numeric/derived answers and must be labeled accordingly. API cost zero.
3. Measure candidate-pool ceilings on multi-session/temporal internal groups: gold-session recall within BM25 top64, selection recall given pool inclusion, and packing coverage. This identifies whether ordering, subset size, or evidence packing is the limiting boundary before adding a neural model. Do not retune the reused validation set. API cost zero.
4. Only after locating loss, trial one packing change or relevance-order change in an isolated development experiment with fixed budgets and provenance. Keep prompt, subset calibration, and memory unchanged in the same trial. Validate independently before live promotion. API cost zero.
5. Prepare the product story around auditable changed commitments and dated sources. HARNESS already has offline fault handling; IDEA needs a useful measured memory behavior; APPLICATION needs a coherent demonstrated workflow and value. No point totals or benchmark-to-rubric conversion are verified. A frontend alone closes none of the current live gaps.
