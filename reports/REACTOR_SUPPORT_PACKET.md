# Reactor t07 session invalidation — operator packet

Team: OpenToVibe. Agent: `agt_0c172edd3340495a`.
Host: `https://t07.api.reactor-hackathon.rxai.dev`.
No access key is included or needed in this packet.

Time window: 2026-10-30 21:43–21:49 UTC.

Only one local Herdr agent/pane was active; no competing local Reactor runner was
found. Our client performed only the two reset calls listed below. Another machine
or server-side operation has not been ruled out.

Observed sequence:

| Operation | History | Outcome |
|---|---|---|
| POST new history, 21:43:39 UTC | f6374884162b4c2fb8a3db5d1cf527a9 | running=true, restarted=true |
| Question ref 1e907a02 | same | closed without answer in 0.92 s |
| Retry ref f56695a6 | same | history_changed; current=452926b11f144022aedafe1d9d7b4fbf |
| POST new history, 21:46:39 UTC | 299413920a324b4d86550991784d36b0 | running=true, restarted=true |
| Question ref bd5b83d9 | same | matching ack cycle1; remote close1000, empty reason, no reply |
| Retry ref 07038a19 | same | history_changed; current=ce463bbbcc0c4414a58015afba58d0b0 |
| Retry against reported current, ref f37a5c22 | ce463bbbcc0c4414a58015afba58d0b0 | previous_pending, 5 safe retries, then history_changed; current=516eb9894d574cbaaaeeb639ebbd8446 |

Please check:

1. Which caller or worker created each unexpected replacement history?
2. Did an agent/provider crash or a startup task overwrite the new history ID?
3. Why did a matching acknowledged question receive clean close1000 without any
   reply, and then leave a pending message behind?
4. Is the reset endpoint returning before the new worker/history is stable?

Minimal local reproduction uses the official client and transport; our wrapper
adds final-line citation instructions and redacted transport diagnostics only:

```sh
# REACTOR_ACCESS_KEY must already be privately configured in the environment.
.venv/bin/python runtime.py --questions smoke-answerable/questions.jsonl --histories data/dev/histories.jsonl --out-dir runs/operator-repro --client reactor_client.py --method bm25 --k 4 --limit 0 --stop-after 1 --execute
```

This is a two-request initial probe (one reset, one question), not permission to
run the full benchmark. Do not run concurrently against this agent.

Machine-readable attempts and close metadata:
`reports/reliability-diagnosis-20261030/attempts.jsonl`.
Checkpoint, plan, evidence hashes, recovery records, and source versions are also
preserved. No predictions were fabricated or manually edited.
