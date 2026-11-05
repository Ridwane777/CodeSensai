# ADR-0046 — Questions & Forms (X4): an `ask_user` tool, answered through the same blocking mechanism as confirmations

- **Status**: Accepted (2026-11-01, validated by the team)
- **Date**: 2026-10-29
- **Deciders**: Ridwane (Lot C), on behalf of Lot D (Valentino) — to be confirmed by the team
- **Lot concerned**: D (`web/questions.py`, `web/server.py`, `web/runtime.py`, `frontend/`), with a new shared tool (`tools/ask_user_tool.py`) also registered in the CLI (`cli.py`)

## Context

[X4] Questions & Forms asks that the user can answer the questions the model
asks in a fluid way (forms, proposed choices). The web interface already had
a form card and a `question` event in its contract
([ADR-0020](0020-interface-web-simulee.md)), but only the simulated engine
produced it: the real agent had no way to ask anything, so the feature was
listed as simulated in `docs/architecture/web/simule-vs-reel.md` and
in issue #62.

The agent loop (`core/agent.py`) only knows tools. Confirmations
([ADR-0015](0015-confirmation-web-synchrone.md)) already solved "the agent
waits for a human in the browser": a synchronous callable blocks the agent's
worker thread, the server publishes an SSE event, and a POST wakes the thread
up. Timeouts, an interruption or a closed tab all end the wait.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| **A tool `ask_user`, with an `Asker` supplied by the interface** (chosen) | No change to the agent loop or the gateway; the model decides when to ask, like any tool; same thread/broker pattern as confirmations; the answers go back through the gateway's output filters (EV2) | The model has to choose to call it; a small model may ask too often or not at all |
| Let the model write the question as plain text and parse it into a form | Nothing to add on the model side | Fragile parsing of free text (what ADR-0003 avoided for tool calls); the turn ends, so the answer arrives as a new user message without the structure |
| A new event type emitted by the core (`Question`) | Explicit in the event contract | Changes `core/events.py` and the agent loop (Lot A) for one feature; the loop would need a way to receive the answer anyway, i.e. the same blocking callable |

## Decision

A tool `ask_user(title, fields)` (`tools/ask_user_tool.py`), registered in the
CLI and the web. It validates the form proposed by the model (at most 8
fields, kinds `text`, `choice`, `toggle`, 2 to 12 options, bounded lengths)
and calls an `Asker`:

- CLI: `terminal_asker` asks each field in the terminal; Ctrl+D means no answer.
- Web: `WebQuestionBroker` (`web/questions.py`), one per turn, emits
  `{"type": "question", "question_id", "title", "fields", "timeout_s"}` and
  waits at most 100 s for `POST /api/sessions/{id}/answer`
  (`{"question_id", "values"}`). The values are checked against the form:
  unknown field, missing answer, wrong type or unknown choice → `400
  INVALID_ANSWER`, and the question stays open; unknown or expired id → `404
  QUESTION_NOT_FOUND`. Interrupting the turn or closing the tab ends the wait.

No answer is a tool failure that tells the model not to guess. The answers
reach the model as the tool result, so the gateway's output filters mask a
secret typed by mistake.

## Consequences

- ✅ The form card of the interface is now fed by the real agent; the frontend
  only needed to translate the event (`engine/wire.ts`) and send the answer
  (`engine/httpEngine.ts`).
- ✅ Same safety properties as confirmations: no answer can be invented,
  nothing waits forever, and a closed tab or an interruption frees the agent.
- ✅ The same tool works in the terminal, so the CLI and the web still offer
  the same tools (`test_meme_agent_que_le_cli`).
- ❌ Whether the model asks at the right moment depends on the model and on
  the tool description; this has only been tested with a scripted model, not
  yet with `qwen3-coder:30b`.
- ❌ The 100 s wait is bounded by `tool_timeout_s` (120 s by default): a user
  who needs longer loses the question and has to answer in the chat.
- ❌ `sensai-schedule` (X5) has no one to answer: the tool is not registered
  there, so a scheduled task cannot ask anything.
- ❌ A sub-agent started by `delegate_task` without a role goes through the
  same gateway and can therefore ask the user too, and nothing tells the user
  which agent asks. The specialised roles of `team_task` (ADR-0038) only see
  their own tool list, which does not include `ask_user`.
- Follow-up: try it with the real model and record the result in the X4 user
  stories; revisit the wait if users find 100 s too short.
