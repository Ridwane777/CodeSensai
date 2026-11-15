# ADR-0015 - Confirmation from the browser: a synchronous broker, without changing the gateway contract

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Meric Gbemetonou (Workstream B), to be approved with Workstream D (which wires the broker into the server)
- **Workstream**: B (`execution/web_confirmation.py`); D is impacted: it must run the agent in a worker thread

## Context
Human confirmation before a risky action (feature A3) exists for the CLI
(`human_in_loop.py`). The tool gateway ([ADR-0006](0006-tool-gateway.md))
calls a **synchronous** `Confirmer`: `(ConfirmationRequest) -> bool`, which
blocks until the answer. In a browser the answer arrives later, through
another HTTP request (`POST /sessions/{id}/confirm`, see
[web-api.md](../architecture/web/web-api.md)), while the request that
started the agent is an SSE stream still open.

Constraints: an explicit yes is the only way to authorize (timeout, closed
tab, failure or ambiguous answer = refusal); the web interface stays a
facade ([ADR-0005](0005-web-interface-facade.md)); Workstream B's code must
not depend on the web framework Workstream D will choose; the gateway does
not change.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| A. **Synchronous broker** (`threading.Event`): the confirmer blocks the agent's thread, `resolve()` wakes it up | Gateway contract unchanged; no framework; testable without a server; same guardrails (only `True` authorizes) as the CLI | One blocked thread per pending request; the agent must run outside the event loop |
| B. `async` confirmer (the gateway `await`s the answer) | No blocked thread on the server side | Changes the `Confirmer` contract of [ADR-0006](0006-tool-gateway.md), hence the gateway, the CLI and their tests; forces the whole chain (ReAct loop, tools) to become `async` |
| C. Polling a session dictionary (the confirmer loops on `sessions[id][confirm_id]`) | Very simple to write | Busy waiting or `sleep`; shared dictionary without a lock or guaranteed cleanup; timeout, closing and duplicates must be redone by Workstream D; hard to test |
| D. Bidirectional WebSocket instead of SSE + POST | A single channel for question and answer | Calls into question the transport contract already documented; we would still need a way to block the agent until the answer, so the confirmer problem remains |

## Decision
Option A. `WebConfirmationBroker` provides a synchronous `Confirmer`. It
publishes a `confirm_request` event via an `emit` function supplied by the
server, then waits at most `timeout_s` for `resolve(confirm_id, approved)`
to be called. Only `approved is True` authorizes; timeout, `close()`, `emit`
failure or unknown id count as refusal. One broker per session; `close()`
when the browser disconnects.

## Consequences
- ✅ The gateway, the CLI and their tests do not change (`git diff main -- src/sensai/execution/gateway.py` is empty).
- ✅ The safety rules are tested once, on the Workstream B side (35 tests in `tests/execution/test_web_confirmation.py`), and not rewritten by each server.
- ✅ No framework imported: Workstream D keeps the choice of FastAPI, Flask or other.
- ❌ **One thread is blocked per pending confirmation**, up to `timeout_s` (60 s by default). Acceptable for one agent per session, to revisit if a server must hold hundreds of simultaneous sessions (threshold not measured).
- ❌ **The agent must run outside the event loop** (worker thread): calling `run_agent_turn` directly in an `async def` would freeze the server during the wait. This is a constraint for Workstream D, documented in `web-api.md` but not verifiable by our tests.
- ❌ **A waiting thread may briefly survive**: the gateway enforces its own timeout (`_run_bounded`, daemon thread) and the broker also waits `timeout_s`. If the gateway expires first, the broker's thread lingers a few milliseconds before cleaning up; it can neither run the tool nor leave a request pending.
- ❌ An answer that arrives after the timeout or after `close()` is rejected (`resolve` returns `False`, the route answers 404): the user who clicked too late must be told; it is up to the interface to show it.
- Follow-up: concurrency tests in `tests/execution/test_web_confirmation.py`; to revisit if the Workstream D server moves to several processes (the broker lives in a single process's memory, the `confirm` route must reach the same one).
