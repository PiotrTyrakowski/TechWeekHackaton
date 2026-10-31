# Fieldbook backend: the context layer

Python standard library only. It serves the dashboard (`frontend/dist`) at `/` and the phone voice app (`voice/`) at `/voice/`. It reads every new input against the firm's jobs.

```
PORT=8788 python3 backend/server.py
```

Keys go in `backend/.env` (gitignored, chmod 600), never in client code:

- `OPENROUTER_API_KEY`: the reader. The default `READER=llm` uses `deepseek/deepseek-v4.1-flash-1017`; set `LLM_MODEL` to change it.
- `ELEVENLABS_API_KEY`: voice. `/transcribe` uses Scribe for speech to text; `/speak` reads a reply aloud.
- `READER=reactor` with `REACTOR_LIVE=1` uses Reactor instead.

## Flow

1. **Messy inputs.** `POST /notes {text, date, jobs, passages?, job?, author_role?, channel?, clarifies?}` saves the input at once as a dashboard row with `reading.status = "reading"`.
2. **Context layer** (`extract.py`). One reader call per input. The reader sees the jobs and earlier messages as evidence `[E1]..[En-1]` and the new input as `[En]`, then answers one line per fact.
3. **Verification.** Every fact must quote the input's own words. The job must be one of the firm's. Statuses come from a fixed list, and amounts and dates must parse. Anything else lands in `rejected` and is never applied.
4. **Agents.** The reading proposes one next step (work order, schedule, order parts, follow-up). It waits until a person calls `POST /actions/<id> {decision: approved|dismissed}`.

`GET /state?since=<version>&wait=25` long-polls. `POST /reset` forgets the inputs. `GET /health` reports the reader and voice status.

## Tests

```
python3 -m pytest backend -q
```

The tests make no model or ElevenLabs calls.
