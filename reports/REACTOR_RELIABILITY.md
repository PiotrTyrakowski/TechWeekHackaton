# Reactor reliability investigation — 2026-10-30

**Team update:** a teammate was concurrently using the same Reactor key and
stateful agent. Shared-agent contention is now the likely explanation. The
historical investigation below is preserved as recorded; server-side debugging
and all Reactor operations are paused until exclusive access is coordinated.

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
