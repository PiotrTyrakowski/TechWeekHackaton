# Session calibration R2

The frozen BM25 session selector improves the fixed validation set from BM25 F1 **78.96 to 86.87**, with precision **86.65** and recall **90.47**. Against the existing dense-hybrid-k4 validation result, its improvement is **1.63 points**, with a paired bootstrap 95% interval **[-1.78, +5.07]**: this comparison remains inconclusive on 88 answerable validation questions. No Reactor calls, resets, credentials, or paid services were used. These are retrieval citation diagnostics, not answer accuracy.

| Scope / method | Answerable | Precision | Recall | Session F1 |
| --- | ---: | ---: | ---: | ---: |
| Validation / BM25 k4 | 88 | 78.88 | 84.64 | 78.96 |
| Validation / previous dense-hybrid k4 | 88 | — | — | 85.24 |
| Validation / frozen calibrated k4 | 88 | **86.65** | **90.47** | **86.87** |
| Development / calibrated, fitted diagnostic | 408 | 86.76 | 89.73 | 86.60 |
| Full526 / calibrated, includes fitted development | 496 | 86.74 | 89.86 | 86.65 |

The validation all-evidence recovery rate is 82.95%; any-evidence recovery is 97.73%. Full526 all-evidence recovery is 81.45%, with 1.95 selected sessions per question, mean 7,193 packed characters, mean retrieval latency 40.5 ms, and p95 51.8 ms on this machine. The full526 +5.88-point F1 difference against prior dense is partly measured on fitted development data and is not an independent generalization estimate.

## Frozen method

`retrieval_calibrated.retrieve(q,h,k=4,method="calibrated",budget=12000)` computes the existing BM25 ranking, takes its first **64 turns**, and groups them by session. Candidates are never filtered by labels. A 30-feature logistic regression estimates each candidate session's relevance. Features cover normalized best/second BM25 score, rank and score gaps, hit frequency, user/assistant hit strength, query-token coverage, turn/session lengths, question cues for multiple facts/counting/time/updates, and interactions between cues and score/role. Features never contain question IDs, history IDs, session IDs, answer text, gold types, or exact question strings. Dates do not enter features; output dates come directly from the current history.

Sessions are sorted by predicted relevance. For each subset size from one to `k`, the selector computes `2 * cumulative_probability / (subset_size + 2 * total_probability)` and chooses the largest value. This is a calibrated **plug-in expected-F1 surrogate**, not the exact expectation of F1. The multiplier of two was selected on internal development. At least one candidate is retained whenever candidates exist. `k` is a session cap, rather than the BM25 turn count. The selected session packs its two best hits and adjacent turns, with an equal character share and original chronological order inside each session. The deployed module uses only the standard library and the frozen 3.6 KB JSON artifact.

## Training and selection isolation

The existing `evaluate.partition` SHA-256 modulo-five split is unchanged: development **433 questions / 408 answerable / 25 unanswerable**, validation **93 / 88 / 5**. The trainer filters questions to development before constructing the label map; validation labels never enter fitting or parameter selection. Unanswerable development sessions supply negative examples. No query-type router or additional pretrained model was introduced.

Exactly two candidate variants were declared: top32 and top64 BM25 turns. The internal holdout assigns a whole history to holdout when `sha256("calibration-r2:" + history_id)[:8] % 4 == 0`. This yields 344 fitting and 89 internal holdout questions. Each variant evaluates L2 penalties `{0.1,1,10}` and mass multipliers `{0.5,1,2,4}` on the internal holdout; the unweighted mean answerable session F1 selects the winner. Both candidate variants and all 24 grid results are recorded in `experiments/calibration-r2/training.json`.

The selected top64 / L2=10 / multiplier=2 configuration scores internal-heldout F1 **85.80**, precision **84.74**, recall **89.14**. One final coefficient fit then uses all 433 development questions. The frozen configuration receives one completed full526 evaluation, with no tuning after examining validation. An earlier evaluator launch failed at module import because PYTHONPATH was absent; it processed no questions and left an empty timestamp directory.

The fixed validation split is by question, not by history. It therefore evaluates held-out questions and must not be described as evidence of performance on entirely unseen histories. The source/data hashes and split rules make the experiment reproducible without storing IDs as model features.

## Remaining failures and uncertainty

All **176 answerable single-session** questions retain full recall. The 92 incomplete evidence sets are concentrated in multi-session **50/121**, temporal reasoning **37/127**, and knowledge update **5/72**. Validation examples include baking-frequency and job-tenure questions with zero recovered evidence; partially recovered temporal questions concern pre-current-job tenure and a book completed a week earlier. Relative dates and event matching are not explicitly represented by this lightweight model.

On fitted development, top64 candidate coverage misses at least one gold session on **10/408** questions; selected subsets miss on **77/408**. Thus most incomplete evidence sets still have potentially recoverable evidence in the candidate pool. Errors can arise from incorrect relevance order, conservative subset size, and the four-session cap. Expanding a candidate pool alone will not address these selection errors. These counts are diagnostic, not independent estimates.

Matched validation comparisons, using existing pre-R2 artifacts, are stored in `analysis.json`. Compared with BM25, 30 answerable validation questions improve, eight worsen, and 50 tie; the +7.91-point paired-bootstrap interval is [+4.30,+11.60]. Compared with dense-hybrid, 18 improve, 16 worsen, and 54 tie. Bootstrap resampling uses seed 42 and 10,000 question-level paired samples; its interval does not account for any historical reuse of the fixed validation set.

Absence confidence is **offline diagnostic only**. Fitted-development maximum relevance probability distinguishes answerable from unanswerable questions with AUROC **0.735**, but average maximum confidence remains high on unanswerable questions (**0.804**, versus **0.901** answerable). Candidate Brier score is 0.0210 on this fitted development set and is optimistic. These results do not support overriding Reactor answers or treating high session relevance as proof that a question is answerable. No abstention action is implemented.

## Reproduction and checks

From this worktree:

```sh
/private/tmp/rxai-dense-20261030/.venv-dense/bin/python train_session_selection.py
PYTHONPATH=/private/tmp/rxai-calibration-r2 /Users/zoga/Dev/Playground/TechWeekHackaton/.venv/bin/python /Users/zoga/Dev/Playground/TechWeekHackaton/evaluate.py --data data/dev --retriever-module retrieval_calibrated --method calibrated --k 4 --out experiments/calibration-r2/final
/Users/zoga/Dev/Playground/TechWeekHackaton/.venv/bin/python -m unittest tests.test_calibrated_retrieval -v
```

NumPy 2.2.6 was used for fitting. Its macOS matrix-multiply path emitted floating-point status warnings even though all resulting parameters are finite (coefficient range -0.765 to +0.677). Runtime scoring uses explicit Python sums, independently avoids that matrix-multiply path, and produced finite probabilities and consistent development F1. No parameter changes were made in response to validation.

Four tests pass: identifiers and extra label-shaped fields cannot affect candidate features; output preserves session/date/role and character budget; expected-F1 selection handles a clear single versus pair and the cap; empty histories and invalid arguments behave correctly. Source and input hashes appear in the model and evaluator summary. Model SHA-256: `a6ad9390c75b8703641995125ccc7b1226811ab9a53447d73576f274c72dd718`.

Main artifacts: `models/session_selection.json`, `experiments/calibration-r2/training.json`, `experiments/calibration-r2/analysis.json`, and `experiments/calibration-r2/final/20261030T222832152993Z/0-calibrated-k4-summary.json`. The inference module never reads the dataset, trainer, or evaluation outputs.
