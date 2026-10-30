# Bounded robustness round: negative result

**Keep the original `calibrated` artifact.** Development augmentation with dev-large did not improve the frozen selector on either reused validation set. The new `calibrated-robust` method is preserved as an experimental negative result; the original default method and model remain unchanged. No Reactor calls, resets, credentials, paid models, or answer-abstention changes were used.

| Reused validation scope | Method | Precision | Recall | Session F1 |
| --- | --- | ---: | ---: | ---: |
| Original dev, 93 questions / 88 answerable | Original calibrated | 86.65 | 90.47 | **86.87** |
| Original dev, same questions | Robust | 85.13 | 89.62 | 85.86 |
| Dev-large, 93 questions / 88 answerable | Dense-hybrid | 68.37 | 79.51 | 70.59 |
| Dev-large, same questions | Original calibrated | 75.28 | 83.62 | **76.90** |
| Dev-large, same questions | Robust | 77.75 | 77.69 | 74.81 |

On dev-large the robust model gains 2.46 precision points but loses 5.93 recall points against the original calibrated model. Mean selected sessions fall from 2.24 to 1.97; all-gold recovery falls from 73.86% to 64.77%. This is consistent with a more conservative selector combined with a smaller candidate pool. The experiment does not isolate the effects of the extra feature, augmented fitting, and selected pool size, so these are plausible mechanisms rather than causal ablations.

The robust-minus-original paired F1 difference is **-1.00 points** on original dev, bootstrap 95% **[-2.56,+0.40]**, and **-2.09 points** on dev-large, **[-5.47,+0.97]**. These intervals include zero, but neither result supports promoting the new model. Against dense-hybrid on dev-large the robust difference is +4.22 points, **[-0.94,+9.14]**. Bootstrap intervals use 10,000 paired question samples, seed 42; they do not account for exploratory reuse of validation.

## Held-out history subgroup

Both validation sets contain 14 answerable questions whose histories also occur in development and 79 questions from entirely unseen histories, of which 74 are answerable. Robust and original calibrated both obtain F1 100% on the 14 shared-history questions.

| Entirely unseen histories, 79 questions / 74 answerable | Original calibrated F1 | Robust F1 | Robust precision | Robust recall |
| --- | ---: | ---: | ---: | ---: |
| Original dev | **84.38** | 83.19 | 82.32 | 87.66 |
| Dev-large | **72.53** | 70.04 | 73.54 | 73.47 |

The unseen-history robust-minus-original difference is -1.19 points on original dev, interval [-3.06,+0.47], and -2.49 points on dev-large, [-6.47,+1.10]. Again, there is no observed robustness gain. Dense-hybrid dev-large unseen-history F1 is 68.76; robust's +1.28-point difference has interval [-3.97,+6.30]. All subgroup metrics and pairwise counts appear in `experiments/calibration-r2-robust/analysis.json`.

## Development-only fitting and freeze

The only fitting questions are the fixed **433 development IDs**, using each question's local text/date/history once from dev and once from dev-large: **866 augmented observations**, representing 408 answerable and 25 unanswerable unique questions. Validation gold never enters fitting or internal parameter selection. The same history-hash split as R2 keeps related questions and both augmentation copies together: **688 fitting / 178 internal holdout observations** (344/89 unique questions). The two copies are not independent samples.

The predeclared grid remains top32/top64 BM25 turns, L2 penalties `{0.1,1,10}`, and expected-F1 mass multipliers `{0.5,1,2,4}`: 24 internal configurations, selected by mean answerable F1 across the two equally sized history variants. Ranking is computed once per query/history and reused across candidate-pool variants. The selected **pool32 / L2=10 / multiplier=2** scores internal-heldout F1 **86.07** on dev and **69.15** on dev-large, mean **77.61**. One final coefficient fit uses all 866 augmented development observations. Extraction, internal selection, final fitting, and hashing finish in **164.7 seconds**, inside the five-minute bound.

The model adds `log1p(history session count)` as feature 31 after the original 30 features. Its standardized coefficient is -0.328. `calibrated` still generates only the original features and loads `models/session_selection.json`; `calibrated-robust` loads the separate `models/session_selection_robust.json`. Identifiers remain bookkeeping and output fields, never model features. The score/subset policy, session packing, and four-session cap otherwise follow R2. Inference remains standard-library-only and reads neither training labels nor evaluator outputs.

The four-session cap remains fixed for this frozen round. The full benchmark of 496 answerable questions contains 11 questions with five gold sessions and three with six: **14 cases cannot recover all gold sessions at cap4**, giving an all-gold ceiling of 97.18% even with perfect ranking. No cap8 model was selected or evaluated in this round.

Development candidate coverage illustrates the smaller-pool tradeoff: dev-large top32 has mean gold-session recall **92.50%** and contains all gold for 354/408 questions; top64 reaches **94.87%**, all gold 368/408. On original dev these figures are 97.17% / 385/408 and 99.17% / 398/408. This does not by itself explain the entire validation recall loss; learned order and subset-size selection also matter. No further configuration was tried after the freeze.

## Artifacts and verification

One completed validation93 evaluation was run per dataset, after freezing parameters. Two initial CLI launches resolved the already-cherry-picked root's older module and failed on the first retrieval before processing any questions. Running `python -m evaluate` from the isolated worktree resolves the intended module. No full526 robust evaluation was run. The validation sets are **reused exploratory checks**, not pristine holdouts, and these metrics measure retrieved-session citations rather than Reactor answers.

Six contract tests pass, including exact preservation of the original 30-feature prefix and equivalence of cached versus freshly computed rankings. All robust coefficients/scales are finite; einsum avoids the macOS matrix-multiply status warnings encountered during the earlier fit. The original model hash remains `a6ad9390c75b8703641995125ccc7b1226811ab9a53447d73576f274c72dd718`. Robust model hash: `0e1d062c7478dce88977cf2a97482dc14d58f1e982c245384bf811abbfe31292`.

The training script, all 24 internal results, source/data hashes, compressed exact development feature cache, two validation details/summary files, and post-freeze paired analysis are preserved. `train_session_selection_robust.py` reproduces training; `experiments/calibration-r2-robust/evaluator_analysis.py` reproduces comparisons from evaluator artifacts and the compressed cache. The trainer generates an uncompressed cache; the repository stores its identical contents compressed with deterministic gzip metadata. Main evaluation command, run once per dataset with its appropriate local-date question subset:

```sh
PYTHONPATH=/private/tmp/rxai-calibration-r2 /Users/zoga/Dev/Playground/TechWeekHackaton/.venv/bin/python -m evaluate --data data/dev-large --questions /Users/zoga/Dev/Playground/TechWeekHackaton/experiments/maximum-score-r2/dev-large-validation-questions.jsonl --retriever-module retrieval_calibrated --method calibrated-robust --k 4 --out experiments/calibration-r2-robust/dev-large
```
