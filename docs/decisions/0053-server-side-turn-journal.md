# ADR-0053 - Turn journal (EV3): a local SQLite store written by the web server and the CLI

- **Status**: Accepted (2026-11-01, validated by the team)
- **Date**: 2026-11-01
- **Deciders**: Ridwane (Lot C), on behalf of the owning lot (Lot D, Christopher, observability) - to be confirmed by the team
- **Lot concerned**: D (`observability/journal.py`, `web/runtime.py`, `web/server.py`, `frontend/src/pages/Journal.tsx`), A (`cli.py` turn loop)

## Context

EV3 (logs and metrics) asks to trace every agent turn: tool called, arguments,
duration, success or failure. Until now the Journal page computed everything in
the browser from the events of the open tab (`state.logs`): nothing was stored,
reloading lost it, the CLI was not traced, durations were measured in the
browser (network included), sub-agent steps showed 0 ms, the time spent waiting
for the model was not measured, and there was no view across sessions.
`src/sensai/observability/` only had a README saying "not written yet".

CodeSensai is a local, single-user tool: the journal has one reader, on the same
machine, and must follow the same privacy rules as the sessions (mode 600,
retention, deletion with the conversation).

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| Keep the browser-only journal | Nothing to store, nothing to protect | Lost on reload; no CLI; durations include the network; no cross-session metrics; does not meet EV3 |
| JSON lines file per day | Simple, `grep`-able | Metrics need a full read; deleting one session's rows means rewriting the file; no transaction between a turn and its tool calls |
| **SQLite store `<data_dir>/journal.db`** (chosen) | Same technology and rules as `sessions.db` (600, one connection per call, `VACUUM` on delete); metrics are one SQL query; delete by session and purge by date are one statement; written in one transaction per turn | One more file holding (filtered) arguments; no standard tooling to view it outside CodeSensai |
| OpenTelemetry traces (OTLP exporter + Jaeger/Tempo) | Industry standard, spans and nesting for free, ready for a multi-user deployment | A collector and a backend to run next to a local tool; a heavy dependency for one user; the arguments would leave the process |

## Decision

- `sensai.observability.journal`: tables `turns` (session, project, `started_at`
  ISO UTC, `model_ms`, estimated `tokens_sent`, `outcome`, `interface` web/cli) and
  `tool_calls` (turn, tool, arguments, `duration_ms`, `ok`, `agent`).
- Arguments go through the EV2 output filter (`guardrails.filter_output`, secrets
  masked) and are cut at 500 characters before being stored.
- Durations are measured **by the server** with `time.monotonic()`: a tool from its
  `ToolCall` to its `ToolReturn` (sub-agent tools around the gateway call);
  `model_ms` = duration of the agent loop minus the main agent's tool time.
- `TurnRecorder` writes once at the end of the turn and never raises: a journal
  failure becomes a log warning, the turn goes on.
- Written by the web turn loop (`WebRuntime._turn`, sub-agent tools included) and the
  CLI turn loop (`cli.main`). Purged with `retention_days` at start (same setting as
  sessions); a session's rows are deleted with `POST /api/sessions/{id}/delete`.
- Read through `GET /api/journal?session=` and `GET /api/journal/metrics?days=`
  (token required); the Journal page shows them with the real server and keeps the
  in-browser view for the simulated engine.

## Consequences

- ✅ The journal survives a reload and reopening a conversation; the CLI and the web
  feed the same file; cross-session metrics per tool and for the model exist.
- ✅ Durations no longer include the network, and sub-agent steps have a real duration.
- ❌ Arguments are stored: filtered for secrets and truncated, but a file path, a
  search query or the start of a written file are still there. Mode 600 and the
  retention purge are the only protection.
- ❌ Durations are wall-clock: a tool's duration includes the time the user took to
  confirm it, and `model_ms` includes Python overhead between events. A sub-agent's
  own model time is inside the `delegate_task` duration, not in `model_ms`.
- ❌ Local only: no export, no alerting, no standard trace format. If CodeSensai ever
  becomes a shared service, OpenTelemetry is the replacement.
- ❌ The CLI does not record the sub-agents' tool calls yet (the web does).
- ❌ The purge is by turn date, the session purge by last activity: in a conversation
  still active after `retention_days`, its oldest turns leave the journal before the
  conversation itself.
- ❌ `tokens_sent` is the same estimate as M2 (characters / 4, ADR-0045), not a count
  from Ollama.
- Follow-up: tested with pytest (scripted model) and vitest on 2026-11-01; not yet
  checked with the real model.
