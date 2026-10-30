# Reactor integration strategies

Offline design audit, 2026-10-30. Grounded in the pinned official participant kit
`f0a317dfa13e7797baae61711cef27a9805bedcc`; see the detailed
[API audit](reactor-deep-dive/api-audit.md) and
[deep dive](REACTOR_DEEP_DIVE.md). No new Reactor performance measurements are
claimed. Live comparisons require a mutually agreed exclusive access window.

## Decision

Use concise, correctly cited evidence-first answering as the operational control.
Compare BM25-4 with the frozen calibrated retriever before promoting either.
Prioritize targeted context preparation and a **small, source-mapped memory
pilot**. Full-history ingestion is permitted but is an expensive baseline, not
in itself an unconventional idea. Native memory may improve recall, but a memory
answer without current evidence labels cannot earn official evidence F1.

The audit starting pipeline was evidence-first RAG, maintaining the mandated
stateful history between questions without deliberate Reactor memory ingestion.
That remains the default. This workstream adds an opt-in targeted preload pilot;
Reactor-driven source discovery remains a proposed experiment. Existing `memory`/`memory-facts` experiments
were external sentence retrieval, not Reactor memory experiments. Their negative
holdout remains relevant evidence against that particular compression scheme;
see [memory-r2.md](memory-r2.md). Do not relabel it as a live memory result.

## Compare A–E

Let `H` be dataset histories, `Q` final questions, `P` total preload parts, and `M`
intermediate requests. Counts below include initial reset and chat operations;
count safe refused retries separately. Each chat request is a complete sequential
turn, not an embedding/batch upload. No published dollar price or token quota was
found in the kit, so these are API/latency estimates rather than monetary quotes.

| Strategy | Initial operations | Expected benefit | Principal risk | Decision |
|---|---:|---|---|---|
| A. Evidence-first | `H + Q` | Small prompts; controllable provenance; cheap to replay | Retrieval misses facts; incidental previous-answer contamination | Required control; improve citations first |
| B. Full native history | `H + P + Q` | Reactor may recover facts absent from the retriever; amortizes ingestion over several questions | Many sequential loads, irrelevant context, unknown recall/latency behavior; still needs evidence for citations | Size offline; defer broad ingestion |
| C. Compact hybrid memory | `H + P + Q`, with small `P` | Persistent user/event context plus original cited excerpts; updates can be linked over time | Compression can drop assistant facts, negations or updates; unsupported summary claims can spread | Most promising native-memory pilot |
| D. Query-specific context | `H + Q` if prepared locally | Better source coverage, chronology, contradiction visibility and date arithmetic without extra Reactor round trips | Overconfident derived conclusions; additional distractors; wrong entity joins | Highest-value low-latency candidate |
| E. Multi-stage Reactor | `H + P + Q + M` | Reactor can identify missing source IDs or resolve a specific ambiguity before the final evidence call | Extra latency, unverified intermediate claims, stale E labels and pending-request complexity | Add only to demonstrated hard cases |

All five are compatible with the official architecture **if Reactor produces the
submitted final answer**, IDs/dates are from the current history, local tools use
only allowed inputs, and predictions are generated without manual edits. The
rules expressly permit local preprocessing/models/retrievers. Paid external
inference is neither needed for this offline phase nor approved by this report.

### A. Evidence-first answering

“Stateless” describes the intended answering policy, not the actual server: the
rules require one persistent Reactor history for all questions of a dataset
history. We cannot turn each question into a fresh stateless call by resetting.
Send the question/date, role-marked source excerpts, and request a concise marked
answer using only the current question's supporting `[E#]` labels. Earlier E labels
must not carry over. The reference should allow an explicit abstention when the
current evidence is insufficient rather than a plausible answer from near misses.

Measure final-answer citations after the official parser/adapter, not source IDs
mentioned in narrative. The existing Luna answer establishes that answer text can
be right while evidence F1 is zero. The revised prompt is not live-proven yet.

### B. Native long-term memory

The documented ingestion path is reset → oldest-first `--text` parts → final
questions. Each part should carry stable session IDs, history-local dates and both
roles; ask for a short acknowledgement and wait for it. Do not put loading replies
into the benchmark results stream. Acknowledgement confirms a reply was received,
not perfect storage or retrieval of every fact. The kit does not expose memory
inspection or server-side retrieval controls.

Preloading does not solve scored source discovery by itself. Options are:

1. Keep the external evidence retriever; use memory to improve reasoning over its
   cited excerpts. This is B+C, with the same citation recall ceiling unless
   Reactor helps discover additional sources.
2. Ask a source-discovery `--text` question against memory, validate the returned
   session IDs against this history, locally retrieve their original turns, and
   ask the final question with those excerpts as official evidence. This is B+E;
   never convert the discovery reply directly into a prediction.

A pure no-evidence memory probe can test recall diagnostically, but it knowingly
has empty mapped citations. Report that limitation and keep such diagnostics
separate from a scored submission candidate. Raw session IDs in final prose do
not enter the official `[E#]` mapper.

### C. Compact structured hybrid memory

Build an event/fact ledger locally from each history, with stable source session
and turn IDs, source timestamp, role, verbatim supporting text, and conservative
entity/event tags. Preserve uncertainty, negation and alternatives. Record both
old and new statements rather than overwriting a fact merely because a later
session contains similar words. A later session timestamp does not necessarily
mean a later event occurred. Never infer a user's choice from an assistant's
recommendation alone.

Load at most one or two bounded ledger parts in the first pilot. Keep **original
excerpts in every final evidence call**. Treat the ledger as navigation/context;
it cannot replace the source mapping or justify a fact absent from the originals.
If one-pass deterministic extraction is too lossy, a local model may later help,
but its quality and compute cost need a separate development-only assessment.

The implemented first pilot is deliberately narrower than a fact/event database:
`reactor_memory.prepare_memory` pools verbatim retrieved excerpts across the
**public questions in one dataset-history group**, deduplicates them, restores
source-date order, and produces bounded `--text` parts. It uses no gold or inferred
answers and assigns no E labels. `runtime.py --memory-mode targeted` loads the
parts before answering, checkpoints each reply, and still sends original evidence
with each final question. Default total serialized preload budget is12,000
characters including headers, so at the default16,000-character message cap it
fits at most one part per history. Empty selection means no preload call.

This is a **query-aware pooled C/D hybrid**, not query-independent native full
history memory. Public future questions influence selection; disclose that fact.
A difference from evidence-only may come from extra selected context, persistence,
or question sharing; it does not isolate a memory-architecture advantage. Add an
identical-context single-call control or a second sequential question diagnostic
before claiming that persistence itself caused a gain. Excerpt bounds do not
establish full-source coverage: retrieval may already have truncated its input.
The proposed fact/update ledger and Reactor source discovery remain future work.

A useful product demonstration is an auditable “what changed and why” user memory:
Reactor links an old commitment, a later update and the source sessions, then
answers a follow-up using current dated evidence. This exercises persistence and
update reasoning more distinctly than merely feeding a longer prompt. It remains
a hypothesis until compared with evidence-only answers. Full-history preload is
the official baseline; source-grounded update navigation is the more distinctive
idea.

### D. Query-specific Reactor context

Retain the calibrated selector's original provenance and add a narrow layer that
makes the evidence easier to use: restore chronological source order where
relevant; include both statements in an apparent update; retain assistant turns;
show the exact operands and deterministic arithmetic when unambiguous dates or
counts can be extracted. Label computed facts as derived and name their original
sources. Include source excerpts alongside every derivation. If an entity or date
is ambiguous, pass the ambiguity rather than resolving it with an unsupported
conclusion.

Packing quality is as important as session recall: the earlier fact-card audit
lost answer spans even when a correct full session was selected. Test snippet
retention and boundary truncation offline, then measure Reactor answers. Do not
promote broader complementary retrieval just because it raises recall; the
previous experiment raised source noise and lowered F1. Keep evidence selection
and context formatting as separate ablations to identify the source of a gain.

### E. Multi-stage interactions

Begin with **source discovery**, rather than an unrestricted request to solve the
same question repeatedly. A source request should return a bounded list of
stable session IDs or “not found,” using only loaded/current history. Validate
IDs; rehydrate original text; final answer uses a fresh current `[E#]` mapping.
If discovery fails, record that failure and use the predefined fallback; never
invent IDs or treat intermediate claims as facts.

A second candidate is explicit update disambiguation: present conflicting original
statements in an intermediate turn, ask which refer to the same event and which
source dates matter, then ask the final question with the same originals and a
fresh marker. This can still amplify an incorrect intermediate interpretation.
Keep it off by default until paired evidence shows benefit. A successful first
`--text` reply does not mean the agent is idle; the next call can legitimately
receive safe `previous_pending` retries.

## Whole-history feasibility: measured input sizes

These are offline measurements of **public inputs only**, not Reactor performance.
All referenced histories were streamed; no gold data was opened. Serialization
was `[session <id>, <date>]`, then `role: content` turns separated by newlines,
with two newlines between sessions. Part estimates divide that string by
`max_chars - 160`, reserving 160 characters for a short per-part wrapper. These
are packing estimates: preserving semantic boundaries and repeating source
headers on split sessions may require more parts. They are not a tested uploader.

| Scope | Referenced histories / final questions | Median sessions / turns per history | Mean serialized chars/history | Estimated parts/history at16k /32k | Total preload parts at16k /32k |
|---|---:|---:|---:|---:|---:|
| dev | 470 /526 | 48 /491 | 496,038 | 31.79 /16.03 | 14,942 /7,536 |
| dev-large | 470 /526 | 473 /4,872 | 4,887,724 | 309.06 /154.02 | 145,260 /72,390 |
| public test (guide estimate; not downloaded here) | 15 /146 | about200 /undocumented | about2,000,000 | about125 /65 | about1,875 /975 |

Dev serialized range: 461,895–521,211 characters; p95 509,973. Dev-large range:
4,567,589–5,255,079; p95 5,099,986. Total serialized text is 233,137,875 dev and
2,297,230,381 dev-large characters. The guide's dev table describes roughly one
history per question; actual public input IDs show 470 referenced histories for
526 questions. The same questions appear in dev-large, so those are scale tests,
not an independent holdout.

Including resets/questions, estimates are **15,938 dev /146,256 dev-large initial
operations at16k**, versus996 for evidence-first. At32k they become8,532 /73,386.
Using the guide's test approximation gives about2,036 operations at16k or1,136
at32k, versus161 evidence-first. The server's currently deployed32k limit remains
unverified; raising the client flag cannot override a smaller server limit.

For latency, use `T = H*t_reset + P*t_load + Q*t_answer + retry_wait`. The kit says
answers typically take tens of seconds; the only completed recorded answer took
46.63 seconds. Loading acknowledgements have not been measured and might be
faster or slower. As a **scenario**, 20–60 seconds per part makes125 parts for one
test history take42–125 minutes; 15 histories take10.4–31.3 hours just for loading.
Do not turn this scenario into a measured cost claim. At five-second loads it is
still2.6 hours for1,875 parts. Compact1–2-part memory would add15–30 load calls to
the test-scale161-operation reference, before any source-discovery interactions.

The sizing computation can be reproduced without gold or API calls:

```python
import json, math, statistics
from pathlib import Path
for split in ('dev', 'dev-large'):
    root = Path('data') / split
    questions = [json.loads(s) for s in (root/'questions.jsonl').open() if s.strip()]
    wanted = {q['history_id'] for q in questions}
    sizes = []
    with (root/'histories.jsonl').open() as stream:
        for line in stream:
            if not line.strip():
                continue
            h = json.loads(line)
            if h['history_id'] not in wanted:
                continue
            blocks = ['[session '+s['session_id']+', '+s['date']+']\n' +
                      '\n'.join(t['role']+': '+t['content'] for t in s['turns'])
                      for s in h['sessions']]
            sizes.append(sum(map(len, blocks)) + 2*max(len(blocks)-1, 0))
    print(split, len(sizes), statistics.mean(sizes),
          {cap: sum(math.ceil(n/(cap-160)) for n in sizes)
           for cap in (16000, 32000)})
```

## Three highest-value live experiments

1. **Citation/transport acceptance gate.** Freeze one reference prompt/evidence
   package; require a correct marked answer, a correct nonempty mapped citation,
   accepted official prediction and local scorer output. Continue a predeclared
   five-question smoke manifest, including abstention and a multi-source case.
   Where Stage1 is one member of Stage2, `H=5,Q=5` needs10 initial operations total,
   not12; preserve and reuse the completed result rather than silently rerun it.
   If Stage1 is separate, account for its additional reset/question explicitly.
2. **Paired evidence/context test.** The executable plan selects 17 questions in
   11 histories: 12 assistant-fact questions in six natural shared histories,
   plus five singleton questions covering other categories and abstention.
   BM25-4, calibrated-4, and calibrated-4 with the implemented targeted-memory
   preload require **95 initial operations: 28 + 28 + 39**. More generally it is
   `3*(H+Q)+P`. Empty memory selection can reduce P; the dry-run manifest is
   authoritative. Keep query-specific formatting D as a separate later ablation
   instead of silently combining prompt, retrieval and memory changes.
3. **Persistent compact-memory pilot.** The shared-history cohort above tests
   first- versus second-question behavior as part of the same 95-operation plan.
   A later permitted source-discovery arm would add one intermediate turn per
   question, validated original-source rehydration, and a separate fresh-history
   baseline. For one two-question history, evidence-only costs 3 operations;
   one preload plus two final calls costs 4; adding discovery before each final
   call costs 6. These are planning formulas, not authorized additional trials.
   Use multiple histories before making benchmark claims. Do not repeat one known cat example as evidence of
   general memory quality. Synthetic fixtures test semantics but are not benchmark
   accuracy. Grouped public-data sequences must preserve supplied dates and order.

For every arm preserve question selection, within-history order, input hashes,
source evidence, prompt version, completed/pending operations and raw results.
Run complete independent arms with fresh history state; never reset between
questions within one arm/history. Counterbalance arm order across different
histories if feasible and record time-of-run effects. Predeclare failure handling
and do not selectively retry wrong or uncited completed answers. Separate reused
smoke diagnostics from subsequent development evaluation. This report defines
strategy priorities; the experimental runner/plan is authoritative for exact
selected IDs and counts.

## Metrics and rubric relevance

Report answer accuracy with unjudged count, actual mapped session evidence F1 on
all answerable questions, abstention recall on unanswerable questions and false
abstention rate on answerable questions. Report final-marker success, uncited and
unknown-citation rates, per-status failures, initial operations, safe refusal
retries, forwarded successes where observed, and reset/load/question/end-to-end
latencies. Include per-question results and category breakdowns. Retrieval F1 is
a separate diagnostic. Official local matching does not replace the final answer
LLM judge; never count “unjudged” as established correct or wrong.

| Rubric (user-provided4+4+4) | Technical opportunity | Proof needed |
|---|---|---|
| IDEA | Source-grounded persistent event/update memory; Reactor selects which original memories to inspect | Demonstrate a task improved by persistence or adaptive discovery over the same evidence-first control; full preload alone is the organizer's baseline |
| HARNESS | Correct current-ref citations; strict user isolation; deterministic preprocessing; durable recovery and complete submission validation | Offline failure-injection tests plus reproducible successful live smoke and paired results, including every failure |
| APPLICATION | Auditable customer/project memory: changed requirements, commitments and recommendations with dated sources | Product team can show a coherent business workflow and saved work; this workstream supplies capabilities and traces, not frontend claims |

No judging points have been earned by documentation or offline retrieval numbers.
The strongest near-term recommendation is reliable A+D, with a small measured C
pilot for a distinctive memory story. Promote additional calls only when their
measured accuracy/citation benefit survives their latency and failure overhead.
