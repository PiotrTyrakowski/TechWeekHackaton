# Reactor reliability — current status, 2026-10-31

**Organizer update:** current integration uses a 600s timeout, 5–10s safe
unforwarded pending/busy backoff, and explicit one-time same-history question
timeout recovery. Normal pending cycles are expected; timeout does not cancel
processing. No automatic timeout reset or foreign-history adoption is allowed.
Verified local citation fallback is permitted. [Current status](PROJECT_STATUS.md)
supersedes older execution details below.

**Offline hardening is implemented; new live behavior remains unverified. No
Reactor calls were made in this workstream.** The shared agent must remain idle
from our side until the team agrees an exclusive window. Earlier invalidations
are consistent with concurrent teammate usage; they do not establish a server
bug. The historical investigation is retained below without changing its logs.

## Current execution contract

`runtime.py` is sequential, dry-run by default, and uses one Reactor history per
dataset history. The local advisory lock covers the normalized agent identity
across output directories, worktrees, and clones for this machine user. This lock
cannot stop another machine, another operating-system user, or direct clients.

Live execution now requires BOTH `--exclusive-access` and `--access-window FILE`.
The JSON records a team agreement; it is **operator attestation, not a remote
lease or proof that another teammate is idle**. Agree that all other users have
relinquished this agent before filling it in. Its schema is:

```json
{
  "owner": "designated-live-runner",
  "agreed_with": ["other-agent-user"],
  "starts_at": "YYYY-MM-DDTHH:MM:SSZ",
  "ends_at": "YYYY-MM-DDTHH:MM:SSZ",
  "base_url": "https://t07.api.reactor-hackathon.rxai.dev",
  "agent_id": "agt_0c172edd3340495a"
}
```

Place this operational file under ignored `runs/`; it contains no access key.
Dates require timezone offsets, the owner and agreed participants must be named,
and the URL/agent must match the run. The runner re-reads the file before every
reset, memory part, and question. It refuses to begin unless the window contains
the entire client timeout plus the 15-second subprocess reserve. An accepted
remote request can still remain pending after a connection loss; expiry does not
cancel remote processing. Coordinate a handoff after such a failure instead of
letting another runner reset automatically.

Example shape after a real agreement (the file is not supplied by this report):

```sh
.venv/bin/python runtime.py --questions smoke/questions.jsonl \
  --histories data/dev/histories.jsonl --out-dir runs/new-exclusive-smoke \
  --method calibrated --k 4 --limit 0 --execute --exclusive-access \
  --access-window runs/agreed-window.json --stop-after 1
```

`--memory-mode targeted --memory-budget 12000` optionally loads the bounded
source ledger before questions. It uses the documented `--text` path and waits
for each reply. These auxiliary replies never enter predictions. This is pooled,
query-aware retrieved context, **not a demonstrated native full-history memory
capability**. Question-specific original evidence is still supplied for citations.

## Fixes and evidence

| Failure boundary | Behavior now | Offline evidence |
| --- | --- | --- |
| Shared access | Named, bounded window plus local agent lock; expiry checked per operation | Missing flag/file, wrong agent, naive timestamps, future/expired interval, insufficient timeout reserve, mid-run expiry tests |
| Reset succeeded but local checkpoint write failed | Recover the exact durably recorded reset response; do not reset again | Injected failure after reset log fsync |
| Memory part succeeded but checkpoint write failed | Recover that exact part in that exact Reactor history | Injected failure after preload reply log fsync |
| Stale earlier successful operation exists | Per-operation random request IDs bind pending state to one attempt | Old successful reset cannot resolve a new uncertain reset |
| Question response durable before local validation failure | Revalidate and recover without asking again | Existing durable-answer recovery test |
| Timeout/closed/refused/error | Stop; do not turn infrastructure failure into an abstention | Timeout and uncertain-reset/preload simulations |
| `history_changed` | Stop; never adopt `current_history_id` | Foreign-history rejection tests |
| Local resume after code/data/evidence changes | Refuse changed manifest | Manifest includes official client/parser, runtime/retrieval/model hashes, exact evidence and memory hashes |
| Misreported answer/citations | Re-parse citations from actual final text and exact supplied evidence; validate history membership and abstention flag | Changed stored final label, foreign label/history, inconsistent abstention tests |
| Uncited real answer | Preserve and score actual empty citations | No label movement from explanation and no prediction repair |
| Successful diagnostics | Preserve redacted stderr on successful as well as failed calls | Successful transport metadata retention test |
| Crash durability | fsync JSONL logs, checkpoints, prediction files, and rename parent directories | Failure-injection tests verify recovery ordering |

`python3 -m unittest discover -s tests -p test_runtime.py` passes **32 runtime
tests**. These simulate lifecycle boundaries and do not show that Reactor memory,
model instruction following, or citation quality succeeds live. Other client and
transport test counts are reported separately by the lead's integrated check.

An offline calibrated five-question targeted-memory dry run planned **5 resets +
5 preloads + 5 questions = 15 initial operations**. All final question messages
fit the 16,000-character preflight, maximum 13,315 characters with the current
prompt. Source ledgers range from 3,070 to 8,269 characters. Safe server refusals
can add request attempts; the live ledger must report these retries separately.
The same smoke without memory plans 10 operations. Neither plan is a live result.

## Recovery policy and remaining limits

A pending operation is persisted **before** its process starts; its raw result is
fsynced **before** advancing state. Only an exact successful durable response can
resolve a crash automatically. A reset response that never reached local disk is
ambiguous and remains blocked. An uncertain question or memory timeout is never
replayed automatically. A truncated/corrupt log stops rather than being repaired
silently. There is no documented read-current-history, enumerate-memory,
request-cancellation, or fetch-pending-answer endpoint in the supplied client.

`--retry-closed` remains a one-time explicit same-history recovery consistent with
the participant guide, inside a valid exclusive window. A closed request may have
been forwarded; its old model output can arrive late. The official client filters
final answers by fresh ref and acknowledged cycle. `--restart-interrupted-history`
permits one explicitly requested reset only after `history_changed` and before any
answer in that dataset history succeeded. It must follow renewed coordination;
never use it to take over an active teammate's history. The obsolete adoption
flag remains disabled. Dry runs cannot consume these retry/reset opt-ins.

Source manifests intentionally refuse resuming historical interrupted runs after
these source changes. Preserve the earlier runs; use their exact original code
to inspect or recover them. Do not edit their predictions or manifests to force a
resume. New live trials need a fresh, explicitly coordinated run.

Remaining live gates: one correctly parsed and cited answer accepted by the
official adapter/scorer; a five-question smoke with every failure retained;
paired controlled trials; then a proposed larger evaluation. Retained earlier
logs still contain only one correct answer with zero Evidence F1. No new success,
accuracy gain, memory gain, or judging points are claimed.

This hardening can support the HARNESS rubric through reproducible fault handling
and honest logs. IDEA points require a useful demonstrated Reactor memory method,
and APPLICATION points require a convincing user/business use case; reliability
alone establishes neither.

---

## Archived 2026-10-30 investigation

The following is the historical report. Its old test count and discussion of a
history-adoption diagnostic describe that earlier revision; they are not the
current operational contract above. Do not follow its adoption diagnostic.

# Reactor reliability investigation — 2026-10-30

**Team update:** a teammate was concurrently using the same Reactor key and
stateful agent. Shared-agent contention is now the likely explanation. The
historical investigation below is preserved as recorded; server-side debugging
and all Reactor operations are paused until exclusive access is coordinated.
The experimental history-adoption flag is now disabled to prevent using a
teammate's or another dataset user's memory. Its failed historical probe below
is preserved, not a recommended recovery procedure.

Status: local fixes implemented and tested; live validation remains blocked by
remote history invalidation. No correctly cited live answer has yet been obtained.
Do not launch the full benchmark.

## Local contention audit

Herdr's inherited caller context names the stopped `agent-factory` session. With
socket permissions enabled, inventory showed only `default` running, with one
Codex agent in one pane (`wG:p1`) at this repository. No second Herdr agent or pane
was running. A redacted process scan found no `runtime.py`, official Reactor
client, benchmark runner, or command referencing our API host. This is a current
local audit, not proof that no other machine/browser or server worker is active.
No Herdr agent was interrupted and no session was stopped.

## Fixed locally

- `reactor_client.py` changes the outbound prompt to require actual supporting
  `[E#]` citations **inside the marked final answer**. The official transport,
  final-answer extraction, abstention detection, and citation mapping are reused.
  Neither predictions nor narrative citations are rewritten.
- Transport diagnostics now preserve matched acknowledgements, frame types,
  error codes, and clean-close code/reason. Headers and message bodies are excluded;
  credential-shaped values are redacted.
- Message-size preflight uses the wrapper's actual prompt. `--stop-after 1`
  checkpoints one answer without changing the five-question manifest.
- Explicit client-only upgrades are recorded and permitted only before a
  successful answer and with unchanged data/evidence/message sizes.
- The documented `history_changed` recovery can rebind once to the server's
  reported current history, explicitly opted in, before any answer in that dataset
  history succeeds. This is diagnostic recovery, not a reliable default. It was
  tested live once and did not restore service. Repeated adoption is blocked.

All 37 local tests pass. These are regression tests, not live success claims.

## Live evidence

The new five-question experiment is `runs/reliable-citations-v1`; its immutable
snapshot is `reports/reliability-diagnosis-20261030/`.

1. Reset returned history `f6374884162b4c2fb8a3db5d1cf527a9`, started
   `2026-10-30T21:43:39.777848+00:00`, `running=true`, `restarted=true`.
   The cat-name question closed in 0.92 s with no final answer.
2. Same-history retry was refused with `history_changed`, reporting current
   history `452926b11f144022aedafe1d9d7b4fbf`. It received no matching ack;
   close code was 4409. No local reset returned that current ID.
3. One recovery reset returned history `299413920a324b4d86550991784d36b0`, started
   `2026-10-30T21:46:39.688307+00:00`, `running=true`, `restarted=true`.
   The question received an ack matching its sent text, cycle 1, then the server
   closed with code **1000**, empty reason, in 1.02 s. No reply arrived.
4. Same-history retry reported current history
   `ce463bbbcc0c4414a58015afba58d0b0`, with `history_changed` and close 4409.
5. One explicit adoption of that reported current history received
   `previous_pending` refusals and nonmatching ack text. The official client made
   five safe retries, then received `history_changed` reporting
   `516eb9894d574cbaaaeeb639ebbd8446`. Total call time was 27.10 s.

Nonmatching acknowledgements may refer to our earlier accepted request or another
sender; they do not establish another actor by themselves. Server logs are needed
to distinguish process/provider restart, reset lifecycle bug, and external reset.

The official client returns the reset POST response unchanged and uses its exact
history ID in the WebSocket URL. Our code issued only the two reset calls recorded
in the snapshot. A matching ack followed by remote close and later history-ID
replacement rules out a local timeout or final-answer parsing failure for that
attempt. The immediate failure is remote session invalidation. Its underlying
cause remains unresolved.

## Metrics and API accounting

New experiment: **0 completed answers**; answer accuracy, evidence F1, and
abstention rates are **not measurable**. It is not legitimate to mark five
incomplete questions as five model errors or abstentions. No unjudged answer was
produced to review.

- 2 reset POSTs, both successful responses.
- 5 question-client invocations plus 5 internal safe retries = 10 question
  request attempts; none returned a final answer.
- **12 benchmark API requests total**, 31.98 s inside client invocations.
- Additional public diagnostic `GET /openapi.json`: one request, HTTP 404.
  This is separate from benchmark/reset counts.
- Before this investigation: 7 benchmark requests, including 3 resets, with one
  completed correct answer and evidence F1 0.000. Its prediction is unchanged.
- Across both live experiments: 19 benchmark requests, 5 resets, one completed
  answer. No full benchmark run was launched.

The previous answer remains `Luna`, gold `Luna`, citations `[]`, official local
result correct, unjudged count 0, answer latency 46.63 s. It cited the correct
session only outside its final answer; no post-processing moved that citation.

## Required external resolution

Ask the Reactor operators to inspect the history transitions and worker restart /
provider logs for agent `agt_0c172edd3340495a`, slot `t07`, during
21:43–21:49 UTC on 2026-10-30. Check for reset calls from another client as well as
agent-startup initialization overwriting the ID returned by POST /history.
`REACTOR_SUPPORT_PACKET.md` contains a credential-free reproduction and log paths.
No support message was sent automatically.

After the service is stable: obtain one correctly cited answer using the wrapper,
then continue the existing five-question plan. Preserve interrupted artifacts and
do not resume against an unverified foreign history. Broader BM25-8 answer tests
remain deferred until this gate passes.
