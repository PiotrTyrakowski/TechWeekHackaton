# Gate 0 — offline protocol validation, 2026-10-31

**Passed locally: 103 tests, zero new Reactor operations. Gates 1–4 remain unverified live.**

The independent baseline check passed all 99 existing tests. The final guarded
run passed those tests plus four new checks. The validator denies real socket
connections, DNS lookups, HTTP requests, and subprocess execution; tests replace
those boundaries with local fakes. Existing access-window fixture files are
synthetic temporary unit-test inputs, not an operational access agreement.

The additional same-user simulation runs the actual runner, citation wrapper,
official asynchronous parser, and prediction adapter. Two questions share one
Reactor history with one reset. `[E1]` maps to `s_old`/Luna on the first question
and `s_new`/Rover on the second; stale previous-ref and ineligible-cycle replies
are ignored. The submitted second prediction cites `s_new`. This establishes
local mapping behavior, not Reactor model instruction-following or memory quality.

The read-only audit reparses the unchanged historical cat reply and reproduces
the preserved prediction through the official adapter and local scorer:
`Luna`, correct answer text, no submitted citations, Evidence F1 **0.0**.
It does not move the narrative citation into the final answer. Source hashes
confirm the three historical inputs were unchanged. The original supplied
evidence is not reconstructed, and no official LLM judge was called.

[Machine-readable validation](final/validation.json) records code/test hashes,
separate simulated and historical evidence, limitations, and zero new calls.
[Full test log](final/tests.log) lists the executed checks. Reproduce into a fresh
directory from a checkout containing the pinned local `official/` kit:

```sh
.venv/bin/python gate0_validate.py --out runs/gate0-new-validation
```

Next experiment: one real cat answer with a correct nonempty citation in its
marked final segment, after explicit cross-machine exclusivity and appointment
of exactly one runner. Initial budget: **one reset + one question = two Reactor
operations**, excluding refused retries or recovery. Monetary pricing remains
unknown; the historical 46.63-second answer is one observation, not a reliable
latency estimate. No retrieval or answer configuration is promoted by Gate 0.
