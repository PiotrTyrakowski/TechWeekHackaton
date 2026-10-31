# Independent read-only evaluation

The evaluation owner independently reconciled the final actual API archive:

- 7/8 completed; seven official-local matches, zero wrong/unjudged completed answers.
- Completed answerable Evidence F1 0.944444 across six outputs.
- Full-planned submission-equivalent scores: 7/8 correct and F1 0.809524.
  Temporal missingness is a submission penalty, not an observed model error.
- 29 operations: 18 client invocations (eight resets, ten questions) plus eleven
  safely unforwarded refusal retries. Three failed invocations, all temporal.
- Six Reactor-cited outputs, one genuine abstention, zero fallback additions.
  Five answer forms are outside the conservative supplemental-attribution grammar.
- Archive hashes and timing reconcile; no named local runners were detected.
- No next-cohort API jobs have launched.

The independent check made no API/credential operations or primary-checkout edits.
The lead separately ran the provided `official/score.py` CLI; its full-scope
output and per-question details are retained beside this file. No organizer-side
LLM answer judge ran.
