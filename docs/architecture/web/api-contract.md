# Contract between the web interface and the core

**Status: draft — to be validated between Workstream A and Workstream D before
web development starts.** This is the document ADR-0005 describes as
blocking: until it is accepted, Workstream D cannot work in
parallel.

## The idea in one sentence

An agent turn does not produce text, it produces **a sequence of
events**. The CLI displays them in a terminal, the web sends them to the
browser as JSON. Both interfaces consume the same source, so they
cannot tell two different stories.

The source is `sensai.core.agent.run_agent_turn()`, which returns objects
defined in `sensai/core/events.py`.

## The events

| Type | Fields | What it is |
|---|---|---|
| `token` | `text` | A piece of the final answer, displayed as it streams |
| `thought` | `text` | The reasoning before acting — to be presented differently from an answer |
| `tool_call` | `id`, `name`, `arguments` | The agent asks for a tool to run |
| `tool_return` | `id`, `name`, `ok`, `content` | The result of that tool |
| `error` | `message` | The turn is lost (model unreachable, etc.) |
| `done` | `reason` | End of the turn — always the last event |

Three rules that matter for display:

1. **`id` links a `tool_call` to its `tool_return`.** Two tools can
   follow each other in the same turn; without this id, the interface no
   longer knows which result belongs to which call.
2. **A tool that fails is not an `error`**: it is a `tool_return`
   with `ok: false`, and the agent continues. `error` means "this turn is
   lost", nothing but `done` will follow.
3. **`done` always arrives**, including after an `error`. It is the signal
   to hand control back: redisplay the prompt in the CLI, close the stream on the web side.

On the Python side, `to_wire(event)` turns an event into a JSON dictionary.
The wire names (`token`, `tool_call`, …) are pinned explicitly in
`events.py`: renaming a Python class will not break the front end.

## The proposed HTTP routes

To be discussed — this is the part that belongs to Workstream D.

```
POST   /api/sessions              -> { "session_id": "..." }
GET    /api/sessions              -> list of sessions (depends on Workstream C)
GET    /api/sessions/{id}         -> a session's history
POST   /api/sessions/{id}/messages
       body: { "content": "..." }
       -> SSE stream of events
POST   /api/sessions/{id}/confirm
       body: { "confirm_id": "...", "approved": true }
       -> 204
```

### The response stream

`POST /messages` does not return a complete answer: it opens an
**SSE** stream (*Server-Sent Events*, an HTTP connection the server keeps
open to push messages). Each event goes out as is:

```
data: {"type":"thought","text":"I need to read the config file"}

data: {"type":"tool_call","id":"1","name":"search_codebase","arguments":{"query":"config"}}

data: {"type":"tool_return","id":"1","name":"search_codebase","ok":true,"content":"..."}

data: {"type":"token","text":"The config"}

data: {"type":"token","text":" is in"}

data: {"type":"done","reason":"final_answer"}
```

The stream closes after `done`.

### Confirmation before a risky action

This is the only place where the web needs more than the core provides.

The agent runs no tool itself: it receives the tool gateway
(`ToolGateway`, ADR-0006), and the gateway asks for confirmation. It
expects a function `confirm(request: ConfirmationRequest) -> bool` (type
`Confirmer` in `execution/gateway.py`), supplied by the interface that
builds it. `ConfirmationRequest` carries the tool, its risk level, the
arguments and the allowed time. The CLI gives it a version that asks the
question in the terminal. **The web must give it one that:**

1. emits a `confirm_request` event in the open SSE stream, with an
   id and the content of the `ConfirmationRequest`;
2. waits for the browser to answer with `POST /confirm`;
3. returns `True` or `False` to the gateway.

`confirm_request` does not exist in `events.py`: it is an event specific
to the HTTP transport, which Workstream D adds on the server side. Better to keep it
there than to make the core depend on a network round trip.

**Two points not to miss:**

- No answer after a reasonable delay = **refusal**, never
  approval. Missing confirmation is not a yes. The gateway
  already enforces this delay (`request.timeout_s`): the web uses it to
  display it, and does not need to count itself.
- If the client disconnects while waiting, the action is abandoned.

## What the web does not do

It does not run the reasoning loop, does not decide which tool to call,
does not format the history its own way. All of that comes from `sensai.core`.
If something is missing, `core/` is extended — the CLI benefits too
(ADR-0005).

## Security — to address from the design stage

Exposing this agent on the web means exposing **code execution** on the
web. A page reachable without authentication lets anyone run
Python on the host machine.

- The API is not open without authentication, not even "just for the demo".
- The Workstream B guardrails (sandbox, secret filtering, human
  confirmation) become the only barrier: they are no longer optional.
- The remote Ollama pod from ADR-0004 must not be publicly reachable.

## Open questions

- Is a `usage` event needed (tokens consumed, duration) for
  observability, or does the trace go alongside the stream?
- How does the interface resume an interrupted stream — replay from the
  start of the turn, or give up?
- Who creates the session: an explicit call, or the first message?
