# Submission answers

## Technology stack and partner tools

- **Languages:** Python 3 (backend and benchmark pipeline, standard library only for the server); vanilla JavaScript ES modules, HTML and CSS for the dashboard and the phone app. There is no frontend framework.
- **Reactor (partner):** the reasoning and memory agent. It writes every final answer in the Memory Retrieval Challenge. It is called through the kit's `client.py`, one Reactor history per dataset history, and each answer must cite evidence `[E#]`. In Fieldbook it is an optional reader (`READER=reactor`) behind the same interface.
- **ElevenLabs (partner):** Scribe speech-to-text turns the owner's voice notes into text. Text-to-speech reads the drafted customer reply aloud. The key stays on the server and is never sent to the browser.
- **Models via OpenRouter:**
  - DeepSeek (`deepseek-v4.1-flash`) is Fieldbook's default reader for new inputs.
  - In the benchmark, DeepSeek scans whole histories for evidence and drafts a second-opinion answer that Reactor checks. The organisers agreed to this setup.
  - Claude Sonnet 4.5 was tried as an alternative reader.
- **Retrieval:**
  - BM25 with a Porter stemmer, plus `bge-small-en-v1.5` dense embeddings, with z-score fusion.
  - The `ms-marco-MiniLM-L-6-v2` cross-encoder reranks the results.
- **Datasets:** the challenge's dev and test sets (146 test questions). For the product, a synthetic set of 192 messages from a small plumbing and heating firm (SMS, WhatsApp, voice transcripts, duplicates, conflicting prices, notes that name no customer).

## Who did what?

- **Wiktor Zoga:**
  - Built the Porządek dashboard: the rules engine that rebuilds quotes, approvals, completed work and payments from messages, the job graph, the action plan and the synthetic dataset.
  - On the benchmark: the retrieval baseline, the reranker and the evidence-selection experiments.
- **Piotr Tyrakowski:**
  - Fieldbook's backend context layer: reading each input with citations, checking every fact against the input's own words, conflict detection, and agent proposals that wait for a person's approval.
  - The ElevenLabs voice app, the English version of the dashboard, and the pitch decks.
  - The benchmark pipeline that runs Reactor: scan, evidence, drafts, Reactor answers and predictions.

## What did you test and what were the results?

- **Benchmark (Reactor).** On 22 dev questions:
  - 64% of answers were matched correct automatically. Another 32% are near-misses that need the judge (for example "in the bedroom, above the bed" against the gold "in my bedroom").
  - Evidence F1 was 0.86, and abstention recall was 100%.
  - The evidence scan found 97% of the gold sessions, and 95% of what it listed was gold. With retrieval added, session recall was 100%.
  - The median Reactor latency was 57 s per question (138 s at most).
- **Fieldbook backend:** 38 automated tests, all passing. They make no live API calls. They cover:
  - quote verification: words not in the input are rejected;
  - invalid values, and jobs that are not the firm's;
  - caching, so the same input is never asked about twice;
  - human approval of agent actions, restarts during a read, the HTTP API, and the ElevenLabs request handling.
- **Dashboard engine:** regression tests pass. They check:
  - replay and the report cutoff;
  - dedupe, and ID collisions;
  - order independence;
  - negated and conflicting approvals.

  A parity harness confirmed that the English version computes the same jobs and totals as the Polish original.
- **End to end with a live model.** One real voice-note text ("new price four thousand six hundred fifty, I will call her tomorrow"):
  - DeepSeek found the right job without being told.
  - It extracted the new price and the call-back date, each quoted from the note.
  - It flagged the conflict with the 4,300 PLN the customer had accepted, and proposed a follow-up for approval.

  It took 55 seconds.
- **Not yet tested:**
  - the full test set (Reactor answers were still being collected);
  - this version of the phone app with real recorded speech: the ElevenLabs keys and calls were checked separately, and the flow was tested with typed notes;
  - any test with real tradespeople;
  - load and deployment.

## Known limitations and next steps

- **Speed:** DeepSeek with reasoning takes 20–55 s per input, and Reactor about 60–90 s. Next step: a faster reader for live use, with Reactor for the hard cases.
- **Data:** everything is synthetic. Nothing is connected to real WhatsApp, SMS or email yet, and there are no interviews with tradespeople and no pricing.
- **Single workspace:** no sign-in, and state lives in one file on one server. The dashboard can be hosted as a static site, but the reading backend needs a host that keeps a server running (not serverless as it stands).
- **Agents propose, they do not act.** Approved steps are not yet sent to customers or suppliers. Next step: send the approved message or order after the person approves it.
- **Risk:** a model can quote the right words but read them wrongly. Every fact therefore keeps its source quote, and nothing changes a job without passing the checks. Customer-facing actions still need approval.
