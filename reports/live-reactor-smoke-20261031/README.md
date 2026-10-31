# Real Reactor development sample — 2026-10-31

Eight real development questions were attempted through t07. Seven completed; all seven matched development gold under the official local scorer. The temporal question did not produce an answer because its history was replaced. No organizer-side answer LLM judge has run.

| Metric | Result |
| --- | --- |
| Completion | 7/8 |
| Official local answer match, full planned scope | 7/8 = 87.5% (one missing transport outcome) |
| Official local answer match, completed outputs | 7/7; zero unjudged or observed wrong answers |
| Actual citation F1, full planned scope | 0.809524; missing temporal output penalized as zero |
| Actual citation F1, completed answerable outputs | 0.944444 across six outputs |
| Unanswerable abstention | 1/1 correct |
| Answerable false abstention | 0/6 observed |
| Calls | 29 benchmark operations: 8 resets, 10 question-client attempts, 11 safe internal refusal retries |
| Failed invocations | 3, all on temporal: closed, history_changed, history_changed |
| Citation provenance | 6 outputs with Reactor labels; 0 fallback additions; 5 forms outside conservative fallback grammar |
| Timing | 1290.33s across active stages; 630.16s in clients |

## Per-question outcomes

| Question ID | Category | Actual submitted answer | Local outcome | Citation F1 |
| --- | --- | --- | --- | --- |
| q_1773242b1801 | unanswerable | INSUFFICIENT_EVIDENCE (abstention) | correct | not applicable |
| q_d4ead82e5cad | single-session-user | Luna | correct | 1.000000 |
| q_e2cc79359e15 | single-session-assistant | The refining processes at CITGO's Lake Charles Refinery include atmospheric distillation, fluid catalytic cracking (FCC), alkylation, and hydrotreating. | correct | 1.000000 |
| q_6eaf85dde884 | multi-session | Five online courses in total — three completed on Coursera plus two completed on edX. | correct | 1.000000 |
| q_61a19ce280f4 | knowledge-update | Yes, your mom is using the same grocery list method as you — the same shared grocery list app. | correct | 0.666667 |
| q_4e61f6554795 | single-session-assistant | +49 (0) 62 32 / 14 23 - 0 | correct | 1.000000 |
| q_8a42fbe85acc | single-session-assistant | +49 (0) 62 32 / 14 23 - 0 | correct | 1.000000 |
| q_53ebfc7819cf | temporal-reasoning | NO RESPONSE — session invalidated | incomplete transport outcome | NOT MEASURED |

## What worked

- User fact, assistant facts, multi-session counting, knowledge-update answering and the unanswerable near miss all completed with locally correct answers.
- The natural two-question history stayed in one Reactor history. Its second question completed after 11 safe previous_pending retries: 204.4s accepted-answer latency, 317.05s client wall time.
- Parser/ref-cycle checks, valid source mapping, checkpointing and automatic scoring accepted every completed prediction. Reactor supplied all submitted citations; no fallback sources were invented.

## Measured limitations

The update answer correctly said the mother now uses the same app, but cited only the later source. Gold requires both earlier/later sessions, so that item has F1 0.666667. The earlier source was not added merely to match gold. A prospective prompt comparison can ask Reactor itself to put a brief, source-cited earlier-to-later comparison in the final. No such candidate has been measured or promoted.

The temporal request was acknowledged then closed after 97.22s. A same-history retry was refused because the history had changed. One explicitly permitted whole-history restart was also replaced within roughly 30s. The restart cap stopped further requests. These are infrastructure/session failures, not wrong answers or abstentions. No foreign history was adopted.

The selected sample includes previously exposed diagnostics and development-trained examples. It is a real API integration result, not a held-out final-test accuracy estimate.

## Next execution

The frozen next cohort has 12 new development questions, two per requested stratum, costing 24 initial calibrated operations. Six BM25 controls are predeclared against those same calibrated results (12 additional operations), followed by a possible two-pair bounded-memory comparison (14 initial operations). None has been launched because the shared history is being replaced.

The public test split has been checksum-verified and preflighted: 146 questions, 15 histories, maximum rendered message 13,185 characters. No test gold was accessed and no test API run was launched. The official README requires predictions.jsonl, code/public repository or archive with runnable README, and a presentation; the exact deadline is not in the repository.

Raw outputs, predictions, attribution, checkpoint, retries, recovery and gold used for scoring are preserved in this directory. `scoreboard.json` provides both scope denominators.
