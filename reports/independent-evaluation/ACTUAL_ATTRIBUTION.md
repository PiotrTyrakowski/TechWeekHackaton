# Actual saved Reactor answer: automatic attribution replay

Measured offline on the original completed Reactor result and its **original
BM25-4 evidence**, not a gold-answer proxy. The separately owned policy is
`verified-direct-v1`, research commit `acd11b8`. Full input/module/scorer hashes,
support records and separate predictions are in
[actual-luna-attribution.json](actual-luna-attribution.json).

| Quantity | Historical unchanged prediction | New automatic-policy derivative |
| --- | --- | --- |
| Real saved answers | 1 | Same 1 |
| Local official matched correct / wrong / unjudged | 1 / 0 / 0 | 1 / 0 / 0 |
| Official evidence F1 on available answerable outputs | **0.0** | **1.0** |
| Reactor-supplied citation sessions | none | none |
| Verified fallback sessions | none | `s_8a377a1e6a80` |
| Unresolved claims from policy | policy not applied | none |
| Public-dev output coverage | 1 / 526 (0.1901%) | Same 1 / 526 |
| Available answerable outputs / public-dev answerable | 1 / 496 | Same 1 / 496 |

The Reactor answer remains `Luna`. Its original explanation cited `[E1]` but its
marked final answer did not. The automatic fallback uses the user-role span
`my cat's name is Luna`, evidence index 0, character offsets **[18:39]**, source
session `s_8a377a1e6a80`, rule `direct_name_v1`. The evaluator separately checked
the exact offsets/span, original same-role history occurrence, same-history source
and original date, actual final-label metadata and official prediction conversion.
No answer, source date, old prediction or raw historical result was changed.
Gold entered only the official scorer after attribution had returned.

The derivative prediction is tracked separately in
[new-policy-predictions.jsonl](new-policy-predictions.jsonl). The full immutable
raw archive, including original evidence, selected original history and policy
source bytes, is retained locally at
`/private/tmp/opentovibe-validity-attribution-v2/`.

For completeness, official full-dev submission F1 with 525 missing predictions
is **1/496 = .002016** for the new policy; this is a missing-output penalty, not
observed model performance on 496 answers. The available-output F1 of 1.0 is
**n=1**, selected by prior diagnostic success. It demonstrates a valid repair of
one missing citation. It does not estimate general fallback precision/recall,
Calibrated-4 behavior, Reactor accuracy, same-user sequence quality, unanswerable
handling or final benchmark gains. There were zero new Reactor requests, zero
external hosted AI calls and no official LLM judge run.

Reproduce with the `evaluate_attribution.py` command in [README.md](README.md),
pointing at the original `runs/live-bm25-4-answerable` directory and the exact
research `attribution.py` file. The older tracked smoke archive omits original
evidence and is deliberately insufficient input for this replay. The evaluator
refuses gold-oracle generation, missing provenance and overwritten output paths.
