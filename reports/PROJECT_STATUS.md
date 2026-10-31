# OpenToVibe — current status and decisions

Updated 2026-10-31. **Real Reactor results are now the primary record.**
[Full actual run, answers, category scores and failures](live-reactor-smoke-20261031/README.md).

| Metric | Actual eight-question development sample |
| --- | --- |
| Completion | **7/8**; temporal blocked by session replacement |
| Correct | **7 locally matched; zero observed wrong/unjudged answers** |
| Accuracy, full planned / completed | **7/8 (87.5%) / 7/7** |
| Actual citation F1, full planned / completed | **0.809524 / 0.944444** |
| Abstention | **1/1** correct unanswerable; false abstention **0/6** observed |
| Failures | **3** failed temporal invocations; **11** safe normal pending retries |
| Operations | **29**: 8 resets, 10 question-client attempts, 11 internal retries |
| Timing | **21m30s** across active stages, including waits/recovery; **630.16s** client time |
| Provenance | Six Reactor-cited outputs; zero fallback additions; no answers edited |

Official scoring is the provided **local dev matcher/session F1**, not organizer
LLM judging or hidden test gold. Missing temporal output is penalized in the
full-planned view; it is a transport failure, not an observed wrong model answer.
This is a small development diagnostic with earlier exposure, not final-test
generalization.

The same-user pair completed in one Reactor history. Its follow-up took 204.4s
after acceptance and 317.05s overall with 11 safe pending retries. Knowledge-update
answering was correct, but one of two gold sources was omitted (item F1 0.666667).
No older source was blindly appended to match gold.

**Execution stopped at the restart cap.** Temporal history `3b13a468…` was
replaced; its same-history retry was refused. One whole-user restart returned
`fc32a3d0…` at 08:19:21 UTC, but after the 30s startup wait the server reported
`c6a52a07…`. No foreign history was adopted. Only this lead ran API requests in
this workstream; no named local runner processes remained after stopping.
Another machine/arbitrary client or server lifecycle activity cannot be excluded.
[Credential-free operator packet](live-reactor-smoke-20261031/support-packet.json).

Lead p1 remains the only designated runner. Other agents are read-only.
Next requirement is genuine exclusive t07 control or operator investigation of
the replacement histories. Do not start another collision loop.

Ready after that blocker clears: 12 new stratified questions (24 initial
calibrated operations), six predeclared matched BM25 controls (12 more), and a
possible two-pair memory comparison (14). Selection is frozen in
`runs/live-expansion-20261031/plan.json`; **none of these has been executed**.

Final public test inputs are checksum-verified: **146 questions / 15 histories**.
Dry-run preflight passed, max prompt 13,185 characters; no hidden gold accessed.
No test API run has been launched. The exact submission deadline remains
unconfirmed; the official README leaves it to kickoff announcements.

Previous Gate-1 archives remain unchanged:
[failed attempt](live-reactor-gate1-20261031/gate1-scoreboard.json),
[successful retry](live-reactor-gate1-retry-20261031/gate1-scoreboard.json).

## Immediate organizer-policy update

| Previous assumption | Corrected decision |
| --- | --- |
| Final citations had to be written by Reactor; fallback prohibited | Verified automatic source attribution is allowed and implemented. Preserve Reactor's answer; record supplied/fallback/unresolved citations separately. |
| Auxiliary external models were merely unapproved | Hosted AI processing of benchmark data is forbidden. Small local models/classifiers and local preprocessing remain permitted. |
| Fast pending refusals suggested failure | 50–60s answers plus 15–30s internal cycles are expected. Retry unforwarded pending/busy with 5–10s backoff; one question at a time. |
| 300s timeout and no timeout replay | Raise default to 600s; explicit bounded recovery in the same history after pending clears. Never reset because of timeout or silently adopt externally changed history. |
| BM25 remained the operational default | User explicitly selects frozen calibrated k4 as the primary baseline. BM25 is a comparison arm. |
| Benchmark might add judging points | Benchmark is included inside HARNESS/SOLUTION 4; IDEA 4 + HARNESS 4 + APPLICATION 4 = 12 maximum. No awarded score claimed. |

Compliance audit found no hosted auxiliary AI clients in tracked inference,
retrieval, training, or experiment Python/dependencies. Network setup code fetches
pinned public tooling/data/local model assets; actual model inference is local.
Reactor remains the sole answer generator. Development-agent use is separate.

## Ownership and integrated work

| Herdr | Isolated worktree | Owned work |
| --- | --- | --- |
| Lead p1 | main branch | Integrated policy/provenance into runtime and reporter; regenerated small gate plan; sole integration owner |
| Research p3 | `/private/tmp/opentovibe-reactor-independent-20261031` | `attribution.py` and 18 tests reviewed/integrated (`cefb8f7`, `cdd3fb7`) |
| Engineering p6 | `/private/tmp/opentovibe-reactor-runtime-reliability` | 600s/client backoff/same-history recovery and source safety integrated (`adb2fce`); ownership handed back |
| Evaluation p7 | `/private/tmp/opentovibe-eval-validity-20261031` | Attribution scoring and 146-ID/per-history coverage utilities integrated (`c52b75f`) |

Shared attribution API:
`attribute_answer(question, history, evidence, result)` returns
`policy_version, reactor_citations, fallback_citations, unresolved_claims,`
`supports, final_citations`. Citation arrays contain session IDs. Support
records include exact retrieved-text spans/offsets also found in the matching
original same-role session turn. No gold or hosted inference enters attribution.

At receipt of the clarification, **fallback was not implemented** in the
integrated runtime. Timeout was 300s, safe-refusal cadence 1/2/4/8s, and timeout
recovery stopped for inspection. Per-user grouping, no automatic timeout reset,
durable checkpoints, and foreign-history rejection already existed.

## Latest implementation and measurements

**179 tests pass** with real-network/subprocess denial, including multi-source
fallback, invalid/negated/wrong-entity support rejection, abstention handling,
same-history timeout/pending recovery, and attribution-failure recovery without
repeating Reactor calls. The default policy is `verified`; raw control is
`--attribution-mode reactor`. Separate durable `attribution.jsonl` stores source
spans, raw final text, supplied/fallback IDs and unresolved claims. Runtime
manifests freeze the policy code; source changes refuse old-run resume.

Lead independently replayed the **one actual saved Reactor answer** against its
original retrieved evidence: unchanged `Luna`, raw F1 **0.0**, new automatic-policy
F1 **1.0**; **0 supplied / 1 fallback / 0 unresolved**. Supporting original user
span: `my cat's name is Luna`, session `s_8a377a1e6a80`. This is **1/526 dev
outputs**, selected by earlier completion; no broad accuracy/fallback claim.
No new answer, hosted AI call, or Reactor operation was used.

All five regenerated runtime commands passed real-input dry runs with exact
manifest matches/no attempt logs. Maximum question prompt: **13,315 chars**;
one prefix-only preload: **4,208**, both under 16,000.
[Current validation](gate0/organizer-update/validation.json),
[current frozen gate plan](gates/organizer-plan-summary.json),
[lead attribution replay](gates/organizer-attribution-replay.json).
Local plan: `runs/organizer-gates-20261031/plan.json`.

Earlier milestone, preserved:

Integrated `cc6e6c6` (Gate 0), `371c73c` (small plan), `21707b7` (research).
**109 tests passed** under real-network/subprocess denial, including true E1
cross-source remapping. Five real-input dry-run commands matched exact manifests;
no attempt logs. Largest prompt 9,686 chars; preload 4,208.

Historical real output remains unchanged: `Luna`, local answer correct,
Reactor-supplied citations empty, raw Evidence F1 **0.000**. There is only one
completed real answer; no official answer LLM judge ran. Lifetime archived calls:
19 benchmark operations, including five resets and five safe refusal retries.
Reattribution must write a new policy-derived artifact, never alter this archive.

[Validation](gate0/integrated/validation.json),
[old frozen plan](gates/plan-summary.json),
[independent research](INDEPENDENT_REACTOR_RESEARCH.md).
Those older plan/source hashes predate the organizer update. Use the regenerated
current plan linked above. Earlier broad proposals remain deferred.

## Experiments and final execution

Primary configuration: **frozen calibrated k4, 12k evidence budget, strict citation
prompt, verified local fallback, 600s timeout, no preload**. Local validation
passed; fresh live behavior remains unverified.
Real comparative answer accuracy, fallback generalization, memory benefit,
sequential reliability, and judging points remain unverified.

Gate 0: local attribution/protocol/recovery tests and immutable-history scoring.
Gate 1: one correct real answer with correct supporting attribution, supplied or
verified fallback, preserving raw provenance. **2 initial operations**.
Gate 2: continue the new frozen eight-question/seven-history manifest, including
temporal reasoning, abstention and a natural pair: **13 additional operations**.
Gate 3: BM25/calibrated pair, **6**; Gate 4: bounded preload, **4** with eligible
exact archived control, otherwise a separately proposed **7**. No automatic chain.
Dollar/token cost is unknown. Record all refusals/retries and unresolved work.

Earliest safe freeze: after P0 integration tests, actual attribution scoring,
one clean cited answer and the short same-user/abstention smoke. Gates 3/4 are
optional if they threaten the first full run. Freeze calibrated/no-preload unless
measured live evidence justifies a change; preserve a complete first submission.

For 146 sequential questions, organizer timings imply roughly **2h38–3h39** for
answers plus cycle settling, before resets, long outliers and recovery. Reserve
**4h execution + 1h recovery + 30min final verification** as a planning allowance,
not a completion guarantee. Deadline is pending user confirmation. Begin the
first full run at least 5.5h before it when feasible, earlier if observed latency
requires. Do not launch automatically.

Before full execution: explicit sole-runner agreement, frozen source/input/model/
attribution hashes, public test input preparation (not yet downloaded locally),
all 146 IDs validated, per-history progress and checkpoint recovery tested,
message preflight, a sufficient exclusive window, and a reviewed small live run.
Never reset between same-user questions. A timeout is not cancellation.

## Decision log

| Decision | Evidence / outcome |
| --- | --- |
| D01 | Keep shared-agent work offline until explicit cross-machine agreement; no local lock can prove it. |
| D02 | Replace automatic expansion with individually reviewed small gates; old 95-operation proposal remains deferred. |
| D03 | Seven-question smoke adds a natural pair; all dev pairs repeat assistant sources, so no cross-source/live generalization claim. |
| D04 | Local 109-test milestone passed; historical raw F1 remains zero. No retrieval proxy presented as answer accuracy. |
| D05 — supersedes earlier citation ban | Organizer explicitly permits verified attribution. Implement automatic supporting-span provenance and score separately from raw labels. |
| D06 — supersedes earlier defaults | Calibrated baseline, 600s timeout, 5–10s pending backoff, bounded same-history timeout recovery. |
| D07 | No hosted auxiliary AI inference. Benchmark belongs inside Harness 4; no unsupported judging score. |
| D08 | Freeze after P0/smoke, reserve first full-run window; further ablations must not endanger complete coverage. |
| D09 | P0 integrated: 179 guarded tests; actual saved-answer F1 0→1 under automatic fallback (n=1), raw archive unchanged; five current dry-run commands pass. Gate 1 still awaits exclusive access. |
| D10 | Actual Gate 1 ran: HTTP 403 then `history_changed`, 0 answers, 3 benchmark operations +1 handshake diagnostic. Preserve checkpoint/logs, do not adopt foreign history or expand. Source of replacement remains unverified. |
| D11 | User-authorized fresh retry passed: actual `Luna [E1]`, gold `Luna`, local correct/F1=1, 2 operations/0 failures, 42.91s answer. Preserve prior failures separately; n=1 does not establish general accuracy or startup-delay causality. |
| D12 | Real eight-question smoke: seven completed/correct, planned accuracy7/8, full-scope citation F1 .809524 (completed .944444), genuine abstention1/1, same-user follow-up317s. Temporal failed closed then two history_changed refusals; one bounded whole-history restart failed. Stop at cap, preserve all29operations and resolve shared-agent interference before scaling. |
