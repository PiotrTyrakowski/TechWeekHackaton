# OpenToVibe: memory retrieval for Reactor

Answers questions about long chat histories. Our code finds the evidence and Reactor writes the answer.

## How it works

1. **Index** (`retrieval.py`): each history is cut into turn chunks (long turns get overlapping windows) and into
   sentences. Both levels are scored with BM25 (Porter-stemmed, stopwords removed) plus dense similarity from
   `BAAI/bge-small-en-v1.5`, each z-normalised and summed. Embeddings are cached per session on disk. The best 60
   chunks, the best 400 sentences and every user sentence are then rescored with the cross-encoder
   `cross-encoder/ms-marco-MiniLM-L-6-v2` (plus a little of the first-stage score), which lifts short single-sentence
   facts ("I bought two Cattleya orchids") above long on-topic answers.
2. **Plan** (`evidence.plan`): the question is classified by its wording as a two-event date difference ("how many
   days apart were A and B", "how many days after A did B"), temporal, "current value", count, "you recommended" or
   plain fact. Two-event questions are split into one sub-query per event, alongside the full question.
3. **Whole-history scan** (`scan.py`): retrieval alone misses facts in 200-session histories, most of all for counts
   and changed values. `deepseek/deepseek-v4.1-flash` (1M-token context) therefore reads each question's whole history,
   in parts of about 100k tokens (part first, question last, so a part's prefix is cached across the history's
   questions), and lists the turns that help answer it as `s_<id> t<turn> | quote`. Our code keeps only listed turns
   that exist in that part and whose quote matches the turn's words. On 22 dev questions the scan found 97% of the gold
   evidence sessions, 95% of what it listed was gold, and with retrieval together recall was 100%.
4. **Evidence** (`evidence.build`): the scanned turns first (clipped around their quote, up to 40% of the budget), then
   the best few whole turns (with the user message before an assistant answer),
   then the best sentences of the whole history, each with its neighbouring sentences for context. These are merged
   per session, sorted by date and labelled with the session date and its distance in days from the question date.
   Relative dates ("yesterday", "two weeks ago", "on March 3") get their calendar date in brackets.
5. **Date help**: for two-event questions our code lists each event's candidate dates, with the sentence that states
   each one (near-misses included on purpose), and precomputes the day differences between them. The model only
   chooses; it does no arithmetic.
6. **Guidance** (`evidence.guidance_for`): the message tells Reactor about near-misses (things that happened to a
   friend or relative), that the latest value wins, that some answers combine several excerpts (totals, differences),
   to list every counted item with its label before giving a count, and to answer with only the answer plus its `[E#]`
   citations (for a changed value, the excerpts with the earlier and the latest value). It should answer
   `INSUFFICIENT_EVIDENCE` only when the evidence never mentions the thing asked about for the user.
   `run.py --reuse` keeps the saved evidence but writes the guidance afresh, so it can change without re-retrieval.
7. **Second reader** (`draft.py`, optional): `deepseek/deepseek-v4.1-flash-1017` through OpenRouter reads the same
   message and drafts an answer three times; the most common answer is the draft (`--samples 3`). `run.py --drafts` adds that draft (and its working) to Reactor's message with the
   instruction to check it against the evidence and give the correct answer either way. On dev the drafter alone
   scored like Reactor and made the same two mistakes; the draft is a second opinion, and Reactor still writes every
   final answer. The team agreed this setup with the organisers.
8. **Reactor**: one Reactor history per dataset history; each question carries its own evidence (`run.py`, through
   the kit's `client.py`). Citations are the cited excerpts' session ids (`predict.py`). Abstention is Reactor's
   `INSUFFICIENT_EVIDENCE`.

## Run

Python 3.11+, `pip install "websockets>=14" sentence-transformers nltk numpy`. The challenge repository must sit
next to this folder (`../memory-challenge`, with the kit in `reactor/` and the data splits extracted).

```sh
printf 'Access key: '; read -rs REACTOR_ACCESS_KEY; echo; export REACTOR_ACCESS_KEY
export REACTOR_BASE_URL=https://t07.api.reactor-hackathon.rxai.dev REACTOR_AGENT_ID=agt_0c172edd3340495a
printf 'OpenRouter key: '; read -rs OPENROUTER_API_KEY; echo; export OPENROUTER_API_KEY
python scan.py --split ../memory-challenge/test --out runs/test \
    --model deepseek/deepseek-v4.1-flash                                     # whole-history scan, ~20 min, ~$3
python run.py --split ../memory-challenge/test --out runs/test --dry-run \
    --scan runs/test/scan/results.jsonl                                     # evidence only, ~15 min
python draft.py runs/test --split ../memory-challenge/test --samples 3      # drafts, a few minutes, ~$1
python run.py --split ../memory-challenge/test --out runs/test --reuse \
    --drafts runs/test/draft/results.jsonl                                  # resumable; ~100 s per question
python predict.py runs/test --histories ../memory-challenge/test/histories.jsonl \
    --questions ../memory-challenge/test/questions.jsonl                    # -> runs/test/predictions.jsonl
```

## Our submission

`predictions.jsonl` was built by `python predict.py runs/test runs/test2 ...` (a later run's answer replaces an
earlier one). `runs/test` holds the first Reactor answers; `runs/test2` holds answers asked with the scan-based evidence
and drafts, plus re-asks. A question Reactor did not answer in time is written as abstained. Every Reactor call and
its checks (right ref, citations we sent, size limit, abstention) are in `reactor_report.md` and `reactor_calls.json`,
regenerated by `python report.py`. The saved messages (`runs/*/evidence/`) are left out of the repository; rebuild
them with `--dry-run`.

Without an OpenRouter key, skip `scan.py`, `--scan`, `draft.py` and `--drafts`: Reactor then answers from the
retrieved evidence alone.

Dev: `python run.py --split ../memory-challenge/dev --out runs/dev --gold ../memory-challenge/dev/gold.jsonl
--limit 40`, then `predict.py` and `python ../memory-challenge/score.py <gold subset> runs/dev/predictions.jsonl`.
`--dry-run` builds and saves every message (`runs/*/evidence/`) without asking Reactor.
`eval_retrieval.py` measures session recall against dev gold; `score_run.py <run> ../memory-challenge/dev/gold.jsonl`
scores a dev run (also `runs/<run>/draft` for the drafter alone) and lists the misses.
