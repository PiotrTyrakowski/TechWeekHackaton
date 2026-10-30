# Citation reliability audit

Status: offline implementation and contract tests complete; live improvement is
unmeasured. No Reactor requests were made for this audit.

## Observed failure

The single completed live answer in
[`live-smoke-20261030T2135/results.jsonl`](../live-smoke-20261030T2135/results.jsonl)
correctly answered `Luna`. Reactor wrote `[E1]` in the explanation **before** its
marked answer, then ended with `# FINAL ANSWER [ref:56451236]: Luna`.
The official client consequently returned `citations: []`, and the official
score detail records answer `correct`, Evidence F1 **0.0**. That prediction remains
unchanged. No correctly cited live answer has yet validated the new prompt.

The explanation does not establish why the model chose that format. A plausible
prompt-level explanation is that the official template separately asks for
citations and a final answer, without explicitly requiring those citations in
the extracted segment. This is an inference, not knowledge of Reactor internals.

## Exact official contract

Sources are the pinned organizer implementation in
[`official/reactor/client.py`](../../official/reactor/client.py) and
[`official/reactor/predictions.py`](../../official/reactor/predictions.py).

1. `build_message` sends `[E1] (source: s_..., date: ...) ...` for each current
   excerpt. IDs must be session IDs; dates come from this dataset history.
2. `final_answers` locates a marker at a line start and extracts the segment
   **after** it, up to the next final-answer marker or end of reply. Despite the
   participant guide's shorthand "only that line", the source accepts subsequent
   physical lines too. A second marker with the same ref replaces the first.
3. `ask` accepts a matching current ref only after an ack whose text matches the
   sent message and a later integer reply cycle. Earlier refs go to
   `late_replies`; interim notes do not become the answer.
4. `citations` scans only the extracted segment for uppercase bracketed `E#`
   labels, including `[E1, E2]`. It sorts labels numerically and maps them against
   the **current request's passage list**. It does not interpret a bare session
   ID or an `E#` outside brackets. We request separate `[E1] [E2]` labels to keep
   extraction and label stripping straightforward.
5. `predictions.convert` removes supported label syntax from answer text and
   deduplicates mapped session IDs. The official converter reports and drops
   unknown labels/IDs; our runtime has stronger rejection checks so invalid
   citations are diagnosed rather than silently repaired for submission.
6. `INSUFFICIENT_EVIDENCE` at the beginning of the extracted answer triggers the
   official abstention convention. With `abstain_on={"agent"}`, conversion emits
   an empty answer and citations. A transport failure remains a failed request;
   we do not select `no-answer` conversion.

An important stateful-history hazard follows from step 4: `E1` can name one
session on question one and another session on question two. The parser has no
way to detect that a model remembered an earlier `E1` and reused it incorrectly.
Valid label syntax and valid session membership do **not** prove factual support.
This risk needs a live multi-question same-history test as well as prompt guidance.

## Outbound prompt changes

[`reactor_client.py`](../../reactor_client.py) retains the exact organizer
transport, final-answer parser, abstention detector, and citation mapper. Its
wrapper changes only outbound instructions and diagnostic observation.

The prompt now asks for one concise marked answer, with no preceding or trailing
explanation, and explicitly scopes labels to the current ref and current
excerpts. It forbids reusing prior reply citations or citing remembered facts
without support in a current excerpt. This preserves usable citation provenance
when native memory is present; memory alone cannot produce an accepted session
citation through this client.

It asks Reactor to keep user and assistant statements distinct, match the actual
person/object/event rather than a near miss, distinguish event time from session
time, use the value applicable at the question date, and combine all required
facts for multi-session answers. These are grounding instructions, not proposed
answers. No derived fact, gold answer, or presumed citation is inserted.

For an answer, the labels must appear on the marked final line. All indispensable
supporting sessions should be cited; several excerpts of the same session need
only one supporting label. Unused retrieved sessions should not be cited. For
insufficient evidence, the prompt requires the exact marked abstention with no
citations. With no evidence, it permits an answer from memory but forbids invented
labels; such an answer necessarily has no mappable evidence citations.

The required-form placeholder no longer ends with a specific `[E1]`, which could
encourage copying that label without selection. A separate syntax example is
explicitly identified as an example. Whether this improves selection requires
paired live measurement.

## Offline validation

Run:

```sh
.venv/bin/python -m unittest tests.test_reactor_client -v
```

All **13 tests passed** at this audit. Added cases exercise the actual official
parsers/converter rather than an imitation:

- Narrative-only citation correctly produces no citation; a cited marked answer
  maps correctly.
- A multiline final segment is accepted, while the following different ref is
  excluded.
- Reusing `E1` with a new evidence list maps to the new session, exposing the
  cross-question hazard.
- Multi-session/grouped labels map, duplicate session IDs deduplicate, and an
  unknown label is reported.
- A memory-only answer has no mappable citations, even if it names a session in
  prose.
- A genuine abstention converts; a timeout is skipped rather than turned into
  an abstention.
- Simulated WebSocket frames include a matched ack, interim citation, stale
  final, and current cited final. The real client and converter retain only the
  current `Luna` answer and `s_cat` citation. This is a local protocol test, not
  model performance evidence.

For 41 previously saved evidence files, using one fixed representative question
and date, the new wrapper added 1,705–1,723 characters over the organizer prompt;
the largest resulting message was 13,301 characters. This checks those saved
inputs only. Runtime must continue checking the actual complete message against
16,000 characters, especially for longer questions or new memory context.

## Live acceptance and metrics

Once exclusive access is agreed, first repeat the known cat question with a fresh
authorized history. Preserve the raw response, extracted answer, mapped labels,
official conversion, and official score. A successful answer must be correct
**and** have its supporting citation in the marked segment. Do not add a label
after receiving a deficient answer or retry until a good answer can be selected.

Next use a frozen diverse sample, including a same-history pair that deliberately
changes label-to-session assignments. Measure separately:

- Final-segment citation coverage on non-abstained answerable questions.
- Unknown-label and unmappable-ID rates.
- Exact per-question citation precision, recall, and official Evidence F1 on
  every answerable question, including false abstentions.
- Answer correctness, unjudged outcomes, abstention recall, false abstention,
  latency, retries, and transport failures.

A label appearing anywhere in `reply` is not a success criterion. Coverage alone
also does not show correct support. The highest-value prompt experiment compares
the existing concise final-line policy with the new current-ref grounding policy
on matched, preselected questions and equivalent per-user memory schedules.
This can improve the HARNESS evidence; no judging points are claimed here.
