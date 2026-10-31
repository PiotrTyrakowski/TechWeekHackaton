# Independent read-only Gate 1 verification

Evaluation owner verified the fresh real run without network, credential, or
primary-checkout changes:

- Official parser extracts `Luna [E1]` for current ref `bce53b2b`.
- Matching-message acknowledgement cycle 2 precedes reply cycle 3.
- E1 maps to original same-history session `s_8a377a1e6a80`, dated
  2023/05/24 17:25. Original user support is at evidence offsets [3959:3980].
- Official prediction adapter reproduces the saved prediction. Official local
  development scoring says correct answer and Evidence F1 1.0.
- Direct Reactor citation; no fallback and no unresolved claim.
- One successful reset and one question: two benchmark operations, zero internal
  retries/failures, same reset-returned history, checkpoint pending=null.
- Answer latency 42.91s. The 30s startup wait was recorded; causality is unproven.
- Archive scope is 1/8 completed. Seven remaining Gate-2 questions are unattempted,
  not observed model errors. All nine archive hashes and original evidence/history
  hashes match.

The previous failed run is retained separately. Across both attempts in this live
round: five benchmark operations plus one separate handshake diagnostic, one
completed answer and two failed question-client attempts. No organizer-side LLM
judge or hidden test gold was used.
