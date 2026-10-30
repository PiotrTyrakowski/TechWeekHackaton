# Reactor API audit

Audited offline on 2026-10-30 against the organizer checkout at
`f0a317dfa13e7797baae61711cef27a9805bedcc`. No Reactor requests or paid model calls
were made. This is the client contract at that revision, not a server audit.

## Scope and evidence labels

- **Documented:** explicitly stated by the participant guide or challenge rules.
- **Source-observed:** directly visible in the shipped Python client/adapter; this
  can clarify or narrow prose documentation.
- **Inferred:** a consequence of that interface, not a measured model behavior.
- **Unverified:** requires coordinated live access or organizer confirmation.

Read sources: [participant guide](../../official/reactor/PARTICIPANTS.md),
[quickstart](../../official/reactor/QUICKSTART.md),
[client](../../official/reactor/client.py),
[predictions adapter](../../official/reactor/predictions.py),
[benchmark example](../../official/reactor/examples/run_benchmark.py),
[challenge README](../../official/README.md), and
[format/submission rules](../../official/format.md). Those files are downloaded by
`bootstrap.py` and intentionally untracked; the commit above pins their contents.

## Memory: the usable guarantee and its limits

**Documented:** an agent retains what it has seen within its active Reactor
history and retains none of that history's contents after a reset. The client
module specifies memory, chat history, pending input and late replies are wiped;
agent configuration remains. A dataset history (`h_...`) is a collection of one
user's dated sessions. A Reactor history is the server-generated identifier of
this agent's active conversation state. They are different namespaces.

One Reactor history must serve all questions of one dataset history, sequentially.
Reset only when moving to another dataset history. Multiple questions within one
history can benefit from earlier evidence and messages; facts are not guaranteed
to be recovered perfectly simply because they were loaded. The guide calls this
long-term memory; it does not document context windows, memory indexing,
compression, summarization, retrieval algorithms, storage limits, retention time,
or model architecture. We cannot say whether a particular old message remains
in the model's immediate context or is recovered by another mechanism.

**Source-observed:** the kit exposes a reset endpoint and a chat endpoint, not a
memory CRUD API. A supplied history ID is sent as a WebSocket query parameter.
There is no documented list/resume-old-history endpoint, fork, snapshot, explicit
memory search, deletion of one fact, or state inspection. Reset replaces the
agent's current history; old IDs are invalidated. It is not a collection of
simultaneously active independent conversations on one agent. Distinct agents
can run in parallel if the organizers issue them.

**Documented:** whole histories may be preloaded with repeated `--text` calls,
oldest sessions first. Each part is one real agent turn, must fit the message
limit, and must receive a reply before proceeding. Include session IDs, dates,
and speaker roles. Request a short acknowledgement. Loaded facts remain only in
that Reactor history. Citation mapping still requires `--evidence` on the final
question. Plain text, remembered raw session IDs, or a browsing result alone do
not create scored citations.

**Our integration at the audit starting revision (`623a740`):** `runtime.py`
preserved one active Reactor history per dataset history and sent each question's
retrieved evidence; it did not preload `--text` or ask intermediate source-discovery
questions. It used Reactor as an answer generator at the end of external RAG, with
incidental conversation carry-over. This workstream adds an opt-in
`--memory-mode targeted` preload, described in [the strategy report](../REACTOR_STRATEGIES.md);
no native-memory retrieval benefit has yet been demonstrated live. The name
`retrieval_memory.py` describes an external local sentence index, not Reactor
memory; its failed holdout must not be presented as a failed Reactor memory
experiment.

## Wire protocol and execution

| Operation | Client behavior | Consequence |
|---|---|---|
| Reset | HTTP `POST /agents/{agent_id}/history`, empty body; bearer auth | Returns `history_id`, `started_at`, `running`, `restarted`; no model answer. A failed/uncertain reset cannot safely be assumed to have done nothing. |
| Chat | `wss://HOST/agents/{agent_id}/ws/chat?history=...`; bearer auth | One connection sends JSON `{"type":"message","text":"..."}` and listens asynchronously. |
| Question | Builds question/date/evidence/instructions into one string | No separate model-native evidence, date, question ID, or citation fields travel on the wire. |
| Raw part | `--text` sends the supplied string verbatim | No answer marker or citation extraction; the first eligible reply completes the call. |
| Acknowledgement | Requires an `ack` whose text exactly equals the sent message | Records acknowledgement cycle; a mismatching ack cannot establish acceptance of this message. |
| Eligible answer | Reply cycle must be an integer strictly greater than the ack cycle | A queued earlier reply cannot answer the new question merely by arriving later. |
| Answer identity | Client generates a random eight-hex ref and asks the model to echo it | Ref is textual convention, not server request id or idempotency key. |
| Result ID | `--question-id` is copied to output only | The benchmark ID is never sent to Reactor. |

See `chat_url`, `ask`, `ask_retrying`, `new_history`, and `main` in
[client.py](../../official/reactor/client.py).

The marker parser accepts one to three leading `#`, case/spacing variations and
`FINAL_ANSWER`/`FINAL-ANSWER`. Canonical output should still be
`# FINAL ANSWER [ref:0123abcd]: ...`. Although the guide says only the final line
counts, the actual `final_answers` function extracts the **segment after a
matching marker until the next marker or end of the reply**. A preceding
explanation is excluded; following lines belong to the segment. If a ref appears
twice, its last segment wins. An eligible matching segment completes the request.
Other-ref final segments are recorded in `late_replies`; eligible replies without
the current marker become `other_replies`. Merely mentioning the ref does not
make an answer. A missing marker eventually times out.

## Evidence and citation details

Each evidence item is `{id, text, date?}`. The ID must be the source session's
`session_id`, even for a turn excerpt. The date must come from this dataset
history: the same session can have different dates in another history. Keep user
and assistant roles. Plain string evidence is accepted but has null IDs and
cannot supply valid session citations.

`build_message` assigns `[E1]`, `[E2]`, etc. by **current passage order** and shows
source ID/date next to each excerpt. `citations` scans only the extracted answer
segment. It recognizes uppercase `E` plus digits inside square brackets, including
`[E1, E3]`, deduplicates and sorts numeric labels, and maps each number back to the
current passage list. It reports out-of-range labels in `unknown_citations`.
Canonical single labels (`[E1] [E3]`) avoid differences between the permissive
citation matcher and label stripper. The predictions adapter removes label text,
deduplicates session IDs, and discards unknown or missing IDs with notes.

**Important inference:** E labels are question-local, not permanent memory IDs.
If a previous question's E1 referred to session A and the current E1 refers to B,
a remembered old E1 could produce a syntactically valid but wrong citation to B.
No parser can detect that semantic confusion. Tell Reactor explicitly that only
the current ref's evidence mapping applies. Preloaded ledgers should use stable
session IDs, never pretend that E labels are globally stable.

Official `predictions.py --histories` validates IDs against the union of all
sessions in that file, not each question's own history. Our runner's per-history
validation is stricter and necessary. Neither adapter nor parser verifies that
cited text actually supports the answer; gold evidence F1 and human inspection
remain necessary. Never fix citation omission by copying labels from explanatory
text or attaching all retrieved sessions after the fact.

`INSUFFICIENT_EVIDENCE` at the start of the extracted answer (case-insensitive,
optional leading nonword punctuation) sets `abstained=true`. It is not enough to
say ordinary prose such as “I don't know.” The adapter skips model abstentions by
default; `--abstain-on agent` submits them with empty answer/citations. It also
supports `--abstain-on no-answer`, but we deliberately do not use transport
failures as semantic abstentions. The scorer includes evidence F1 for every
answerable question even when the system abstains.

## Dates and time

`parse_question_date` accepts the supplied slash-date/weekday form or ISO date
with optional `HH:MM`; it validates the actual calendar date and weekday. Output
is ISO wall-clock time, without adding a timezone. `build_message` tells the
agent to treat that moment as now and ignore its real clock. Session dates are
passed through as one-line strings, not parsed or normalized by `load_evidence`.
Dates are prompt content, not a server clock override. Relative dates, event dates
inside a session, and source session timestamps must remain distinct.

## Limits, lifecycle, and retries

| Constraint | Audited behavior | Status |
|---|---|---|
| Message size | Client default 16,000 Python characters, including instructions/question/date/evidence; `--max-chars` changes this local preflight | Source-observed |
| Server size | Guide says 32,000 at event start, changes announced by support; `too_large` reports actual limit/size | Documented; current deployed value unverified |
| Parallelism | One question at a time per agent; another chat can cause `busy`; unfinished prior work can cause `previous_pending` | Documented |
| Safe automatic retry | Only `busy` or `previous_pending` **and** `forwarded is False`; delays 1, 2, 4, 8, 8... seconds within one deadline | Source-observed |
| Timeout | Default 300 seconds, CLI/env override; includes retries, does not prove cancellation or lack of execution | Source-observed/inferred |
| `history_changed` | Old history invalidated; reports `current_history_id`; no automatic retry or adoption | Source-observed |
| `history_resetting` | Refused; guide suggests retry later; not in automatic retry list | Source-observed |
| Close | Exit 5; may reflect reset, stopped agent, access change, or provider restart | Documented; particular cause requires evidence |
| Rate limits | No request-per-minute, token quota, pricing or total-context quota found in audited kit | Undocumented, not “unlimited” |
| Reset failures | HTTP409 busy/reset; HTTP503 `still_stopping` or `restart_failed`; latter may already have installed the new history | Documented |

`history_required`, `one_question`, `permission`, and `unsupported` are additional
mentioned refusal codes. Every error must remain distinct from an answer.
`ask_retrying` preserves late replies across safe retries. The CLI outputs one JSON
object even for most failures, with exits 0/2/3/4/5. `refused` output does **not**
retain the server `forwarded` flag, although the internal retry decision uses it;
keep raw diagnostics if future recovery requires distinguishing refusal origins.

The guide's generic suggestion to use a server-reported current history is unsafe
for this shared team agent: it may contain a teammate's memory. Local locks cannot
coordinate another machine. Never adopt or reset another active user's history.

## Browsing

**Documented:** Reactor can visit public pages and can query a team's public search
URL when told about it. This is useful for adaptive evidence discovery and makes
an agent-operated memory search conceivable. The client exposes no structured
browser tool API, tool-call transcript, custom tool schema, or authentication
contract for that search. Actual browsing reliability, query syntax, returned-page
size, tool latency and citation behavior require live experiments. Do not publish
private data or access keys to make a URL browsable. Even if browsing finds a
correct source, the final call still needs the original excerpts in current
`--evidence` to create official citations.

## What the interface does not establish

The kit establishes statefulness and an allowed ingestion path; it does not prove
perfect recall, trustworthy self-confidence, a particular model provider, memory
architecture, search policy or exact operating cost. The challenge README calls
it a fast instruct model and warns that date arithmetic/counting can be more
reliable in local code. Treat native-memory benefit, interference, latency growth,
long-input quality, cross-question contamination, and multi-stage value as
empirical questions, not as existing capabilities we have already demonstrated.
