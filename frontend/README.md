# Fieldbook dashboard

A light app with no framework and no dependencies. Open it over HTTP, not file://.

- With the context layer: `PORT=8788 python3 backend/server.py`, then http://localhost:8788/ (dashboard) and http://localhost:8788/voice/ (phone voice notes).
- On its own (rules engine only): `npm run dev`, then http://localhost:4173.
- Engine tests: `npm test` (Node 20+).

## What works

- Import JSONL/JSON (up to 5 MB), dedupe by source_id, refusing ID collisions.
- Quotes, approvals, completed work and payments rebuilt from messages.
- Overview with the four-stage workflow (messy inputs → context layer → verified context → agents), an interactive job graph, field history, sources, search and an action plan.
- Messages added by hand: any channel (chat, SMS, voice note, short note, document, correction), from the customer, owner or crew. With the backend running, each one goes to the context layer, which reads it against the job's history and returns verified facts. Each fact is quoted from the input. You also get conflicts, what is still unknown, and one proposed next step that waits for a person to approve it.
- Four replay events, an explicit report clock, state export, localStorage.

## How the context layer fits

`context.js` sends each new input to `POST /notes`. It sends the jobs as `engine.js` sees them and up to 12 earlier messages, then follows `/state`. Rows that come back carry `reading.facts`, and `engine.js` applies those instead of its own regex rules. Without the backend the app runs on the rules engine alone, so it still works as a static site.

## MVP limits

The data is synthetic. Rule parsing covers selected phrasings, not free speech. Nothing is sent to customers: copying a draft does not close the item. There is one workspace per device, with no sign-in. Payments are confirmations the owner records; there is no bank integration.

SourceMessage contract: source_id, sent_at (ISO 8601), raw_text, channel, author_role (owner/customer/worker/supplier), thread_id, contact_key, conversation_title. Optional: attachments, job_context, clarifies_source_id, reading.

Starting state of the large demo on 30 Oct 2026: 20,150 PLN of quotes, 26,900 PLN of agreed work, 3,750 PLN of work done but not paid, and 9,150 PLN of confirmed payments. There are 13 tasks and 4 unidentified notes.
