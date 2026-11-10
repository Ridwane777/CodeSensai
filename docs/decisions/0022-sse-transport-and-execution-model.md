# ADR-0022 — One turn = one SSE stream opened by POST; the agent runs in a thread

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Christopher (Workstream D)
- **Workstream**: D (affects A, which wrote the contract, and B, whose gateway enforces confirmation)

## Context
Written **after** the user stories [US-WEB-1 to 4, 7 and 15](../architecture/web-api.md), which set the expected
behavior: streamed answer, confirmation with a timeout before a risky action, browser disconnection, interruption,
one turn at a time, clear errors.

Workstream A already chose the principle ([api-contract.md](../architecture/web/api-contract.md)): `POST /messages` opens an SSE stream.
What remains is deciding **how the server implements it**, because the core imposes two constraints that the skeleton in
[web-api.md](../architecture/web/web-api.md) did not respect:

- `run_agent_turn` is a **synchronous**, blocking **generator**;
- confirmation is a **synchronous function** `Callable[[ConfirmationRequest], bool]`, and the gateway requires
  a result that `is True`: a coroutine would always be refused.

An asynchronous server iterating the generator directly would block its loop, and the confirmation, which waits for a
request that this same loop would have to serve, would deadlock (gaps 1 and 2 in [web-api-alignment.md](../architecture/web/web-api-alignment.md)).

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| WebSocket (one bidirectional channel per session) | A single channel for events, confirmations and interruption; controllable reconnection | More code (protocol, ping, resume), less simple authentication, outside the contract already written by Workstream A |
| Repeated polling | No long-lived connection | Latency of word-by-word answers, useless load, all the drawbacks without the benefits |
| `GET` + `EventSource` for the stream, separate `POST` for messages | Automatic browser reconnection | Does not support header authentication (`EventSource` sends no custom header), separates a message from its stream, and reconnection would replay a turn we cannot resume |
| Rewrite the core as asynchronous | More natural server | Touches Workstreams A and B's `core/` and `execution/` for a web-only need; out of scope |
| **`POST /messages` returns the SSE stream; confirmation and interruption via separate `POST`s; the agent runs in a thread** | Matches Workstream A's contract; the core is not modified; tested end to end (15 tests) | See the drawbacks |

## Decision
1. `POST /api/sessions/{id}/messages` replies with `text/event-stream` and stays open for the whole turn. The client reads the stream with `fetch` (not `EventSource`).
2. Confirmation (`POST /confirm`) and interruption (`POST /interrupt`) are separate requests, which the server ties to the current turn by the session identifier.
3. **The agent runs in a thread**; its events reach the asynchronous loop through a queue; one action at a time per session (`409` otherwise), several sessions in parallel.
4. **The confirmer is an ordinary function** that publishes `confirm_request`, then waits on a `threading.Event`. It times out **slightly before** the gateway (0.1 s): a late answer gets `404`, not a misleading `204`.
5. No answer in time, browser disconnection or interruption = **refusal**; never an acceptance by default.
6. A broken stream is **not resumed**: the turn is abandoned and does not enter the history; the client resends its message. (Question left open by Workstream A: this is our answer.)

## Consequences
- ✅ The core and the gateway stay unchanged; the CLI and the web consume the same loop.
- ✅ The stories' behaviors are checked: `done` always last, `tool_call` and `tool_return` paired by `id`, refusal on timeout, closed tab, interruption, two sessions without mixing.
- ❌ **No automatic reconnection**: `EventSource` cannot `POST`. A network drop mid-answer loses the turn; the user must resend their message.
- ❌ **One thread per active turn.** Negligible for individual use; to be capped and revisited if several people use the same server.
- ❌ **Interruption is cooperative**: a Python thread cannot be killed. It takes effect at the next event; a model call already sent or a running tool (a code execution, for example) finishes before stopping, within its own timeouts.
- ❌ **An intermediary that buffers responses** (some proxies) breaks word-by-word streaming; the `X-Accel-Buffering: no` header helps, without a guarantee.
- ❌ **Measured against a fake Ollama**, on a single machine, with no load test; behavior with a real model is not demonstrated.
- Link with [ADR-0015](0015-synchronous-web-confirmation.md) (Workstream B, written in parallel): the two decisions agree (synchronous confirmer, agent in a thread). Point 4 will be implemented with Workstream B's `WebConfirmationBroker` rather than the prototype's confirmer; the 0.1 s timeout margin should be carried into the broker if Workstream B accepts it.
- Follow-up: confirm with Workstream A (questions 1 to 5 of [web-api-alignment.md](../architecture/web/web-api-alignment.md)). **Revision threshold**: if more than a few parallel active sessions are needed, move to a bounded thread pool or revisit the transport choice.
