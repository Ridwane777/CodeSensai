# Aligning Lot D with Lot A's web specification

*Version of 2026-10-14, reviewed after merging `main` the same day, with an update on 2026-10-29.* This document links three things: the web server specification written by Lot A
([web-api.md](web-api.md), [api-contract.md](api-contract.md)), Lot D's
[web server user stories](../../architecture/web-api.md), and the interface (`frontend/`). It is the basis of
ADRs [0020](../../decisions/0020-interface-web-simulee.md), [0022](../../decisions/0022-transport-sse-et-modele-d-execution.md),
[0023](../../decisions/0023-acces-a-l-api-web.md) and [0024](../../decisions/0024-extensions-du-contrat-web.md).

**Update on 2026-10-29.** This page is a dated record: sections 2 to 7 describe the state of 2026-10-14 and are
kept as written then (translated). Since then the real server shipped ([ADR-0035](../../decisions/0035-serveur-web-reel.md)),
and PRs #99 to #103, merged on 2026-10-29, added: the `ask_user` tool, the `question` event and
`POST /api/sessions/{id}/answer` (X4, [ADR-0046](../../decisions/0046-ask-user-tool.md)); real `agent_handoff` relays for
`delegate_task` and `team_task` (A2, [ADR-0047](../../decisions/0047-real-agent-handoffs-in-the-web.md)); share links
`POST /api/sessions/{id}/share`, `GET /share/<token>` and `POST /api/shares/<token>/revoke` (X3,
[ADR-0048](../../decisions/0048-share-links.md)); and `POST /api/sessions/{id}/delete`. These three ADRs are still
Proposed. None of this was tried with the real model: only automated tests with a scripted model, and a headless
browser run without a model. Rows touched by this update carry a "2026-10-29" note. The current list of what is
real and what is simulated is in [simule-vs-reel.md](simule-vs-reel.md).

**Order followed, at the team's request:** user stories first, to fix the expected behaviour,
then decisions. Writing the stories showed points the specification did not cover (section 3)
and errors a quick read does not show (section 2).

**What was done, and what was not (2026-10-14).** No server was delivered. I wrote a throw-away prototype
(`docs/conception/web_facade_spike.py`) and 15 end-to-end tests (`tests/web/test_web_facade_spike.py`) with the
real agent loop, the real tool gateway and a fake Ollama, to check that the decisions hold before writing them.
The front end was not yet aligned: that was the next step (section 5).

## 1. What is taken as is

- An agent turn produces a **sequence of events** (`token`, `thought`, `tool_call`, `tool_return`, `error`, `done`), defined in `sensai/core/events.py`; the web does not rewrite the loop (ADR-0005).
- `POST /api/sessions/{id}/messages` opens an **SSE** stream of `data: <JSON>` separated by a blank line, closed after `done`.
- `done` is always the last event, including after an `error`; a failing tool is a `tool_return` with `ok: false`, not an `error`.
- Confirmation before a risky action goes through a `confirm_request` event and a `POST /confirm` answer; no answer in time means a refusal.
- The API is never open without authentication.

## 2. Gaps found in `web-api.md`

Each row was checked in the code merged into `main` or by the prototype. They are to be confirmed with
Lot A; I did not change their document.

| # | `web-api.md` says | What the code or the prototype shows | Proposed fix | Severity |
| --- | --- | --- | --- | --- |
| 1 | The web confirmer is an `async def confirm(...)` function | The type is `Confirmer = Callable[[ConfirmationRequest], bool]`, and the gateway requires `... is True` (`gateway.py`, `_confirmed`). A coroutine is not `True`: **every risky action would be refused, with no visible error** | **Synchronous** confirmer waiting on a `threading.Event` (prototype) | Blocking |
| 2 | The skeleton iterates `run_agent_turn` inside an `async def event_stream` | `run_agent_turn` is a **synchronous** generator: it blocks the event loop, and the confirmation, which waits for a request served by that same loop, **deadlocks** | The agent runs in a thread, events go through a queue (ADR-0022) | Blocking |
| 3 | `print(f"Événement: {event.type}")` | Events are `dataclass`es with no `type` attribute; it only exists in `to_wire()` | `to_wire(event)["type"]` | Misleading |
| 4 | `ToolReturn(..., network_error_code=None)` | This field does not exist (`events.py`: `id`, `name`, `ok`, `content`) | Remove it from the example | Misleading |
| 5 | `ToolResult.data` is "Structured data (JSON on the wire)" | `run_agent_turn` only copies `ok` and `content` into `ToolReturn`: **`data` is never sent** | Either fix the sentence or extend it (ADR-0024) | Misleading |
| 6 | `ConfirmationRequest = {"tool": ..., "risk": Risk.EXECUTE, ...}` (a dict) | It is a frozen `dataclass`: `request.tool`, `request.risk.value`… | Show attribute access | Misleading |
| 7 | `settings = get_settings()  # Charge depuis prompts/config.yml`, model `qwen2.5-coder:7b` | Config is `config.json` (`DEFAULT_CONFIG_PATH`); default model is `qwen3:8b` (ADR-0004) | Fix the file and the model | Misleading |
| 8 | `GET /sessions/{id}` returns a `timestamp` per message; the list returns `session_id`, `last_message_at` | `SessionStore` keeps **no** per-message timestamp; `SessionInfo` exposes `id`, `project`, `title`, `created_at`, `updated_at`, `message_count` | Align fields on `SessionInfo`, remove per-message timestamps | Misleading |
| 9 | The `confirm_request` event carries `id`; the answer carries `confirm_id` | Two names for the same thing, and `id` already means the tool call in `tool_call` | `confirm_id` everywhere | Ambiguous |
| 10 | `ToolPreferences(disabled=[...], modes={"write_file": "ask"})` | Fields expect a `frozenset` and `Mode` values; `ToolPreferences.from_dict` accepts plain dicts | Use `from_dict`, or the exact types | Misleading |
| 11 | The skeleton does not put the user's message in the history, writes `"..."` instead of the answer, keeps confirmations in `sessions[...]["confirm_x"]`, has no authentication and uses a `registry` never defined | None of these pieces would work as is | Tested prototype (section 6) | Incomplete |
| 12 | `done.reason`: `final_answer`, `max_iterations`, `error` | Nothing for an interruption asked by the user | `interrupted` (ADR-0024) | Missing |

Errors 1 and 2 are the most serious: the skeleton, copied as is, **would seem to work for everything except
risky actions**, which would all be refused, or would block the server at the first confirmation.

### State after merging `main` (2026-10-14)

In the meantime, Lot B delivered `WebConfirmationBroker` (`src/sensai/execution/web_confirmation.py`,
[ADR-0015](../../decisions/0015-confirmation-web-synchrone.md), 35 tests) and updated `web-api.md`. Rechecked row by
row on the merged version:

| # | State | Finding |
| --- | --- | --- |
| 1 | ✅ **Fixed** | The confirmer is synchronous (`broker.confirmer`); `web-api.md` says not to rewrite it by hand. |
| 2 | ✅ **Fixed** | The skeleton runs the agent in a thread and passes events through a queue, as in [ADR-0022](../../decisions/0022-transport-sse-et-modele-d-execution.md). |
| 3, 4, 6, 7, 8, 10 | ❌ Still there | `event.type`, `network_error_code`, `ConfirmationRequest` as a dict, `prompts/config.yml` and `qwen2.5-coder:7b`, per-message timestamps, `ToolPreferences` with lists and strings. |
| 5 | ❌ Still there | `ToolResult.data` still announced as "JSON on the wire". |
| 9 | ⚠️ **Now in the code** | The broker emits `"id"` in `confirm_request`, and the route reads `"confirm_id"` in the answer. The interface must read `id` in the event and send back `confirm_id`, or Lot B renames the key. Our prototype uses `confirm_id` on both sides: to align with the broker. |
| 11 | ◐ Partly | History passed to the model, broker closed on disconnect; still a `registry` not defined, no history saving and no authentication (the document says so itself). |
| 12 | ❌ Still there | No `done.reason = "interrupted"`. |

Consequence for Lot D: the real server **will reuse `WebConfirmationBroker`** instead of the confirmer written in
the prototype; the tested behaviour stays the same (only "yes" allows, timeout, closed tab).

## 3. What Lot A's contract does not cover

The user stories showed needs with no answer in the specification. Each has a story and a
fallback behaviour if the extension is refused.

| Need | Story | What it takes | Touches the core? | If refused |
| --- | --- | --- | --- | --- |
| Stop or redirect the agent (X2) | US-WEB-7 | `POST /interrupt` and `done.reason = "interrupted"` | Yes (one more value) | The front cuts its connection; the server drops the turn on disconnect |
| Edit a message and branch (X2) | US-WEB-8 | `POST /fork`: a branch is a new session | **No** | Branches in page memory, lost on reload |
| Form to answer the agent (X4) | US-WEB-9 | `ask_user` tool + `question` event + `POST /answer` — *2026-10-29: done in `main` (#99, ADR-0046, Accepted): `question` event with `question_id`, `title`, `fields`, `timeout_s`; `POST /api/sessions/{id}/answer` → 204, 400 `INVALID_ANSWER`, 404 `QUESTION_NOT_FOUND`; 100 s timeout* | No (it is a tool) | Question asked in the conversation |
| Export a session (X3) | US-WEB-10 | `GET /export?format=json\|md` — *2026-10-29: the route exists in `server.py`; the Export page still builds files in the browser* | No | Browser-side export |
| Share by link (X3) | US-WEB-11 | Share routes, opaque token, expiry — *2026-10-29: done in `main` (#101, ADR-0048, Accepted): `POST /api/sessions/{id}/share`, `GET /share/<token>` (no token, no script, 7-day expiry), `POST /api/shares/<token>/revoke`; revoke button on the Export page since 2026-10-31; the fake link stays only with the simulated engine* | No | Fake link, announced as such |
| Usage and duration (EV3) | US-WEB-12 | `usage` event — *2026-10-29: still not sent by the server* | Yes | Estimate flagged as such |
| Rich tool data (R1, T2, T4) | US-WEB-2 | `tool_return.data` (sources, traceback, diff) — *2026-10-29: the `write_file` confirmation card shows the server's diff (#103); RAG sources come as a separate `rag_sources` event* | Yes | Raw `content` only |
| Profile, config, health (M1) | US-WEB-6, 16 | `/profile`, `/config`, `/health` — *2026-10-29: the routes exist; the Memory page still shows demo profile data. Update on 2026-10-29: the Memory page now reads `GET /api/profile` and `GET /api/facts` and adds/forgets preferences through `POST /api/profile/preferences` and `POST /api/profile/forget`* | Yes (tests) | Real |
| Secrets in the model's text (EV2) | US-WEB-14 | Filtering the streamed text | Yes (Lot B) | **Documented residual risk** |

## 4. From the real stream to the interface

The interface has its own display model (reasoning steps, cards). For it to consume the real stream, there must be a
single adapter between Lot A's stream and that model, **the same for the real server and the simulated engine**.
Otherwise the demo proves nothing about the integration.

| Stream event (Lot A) | Becomes in the interface | Notes |
| --- | --- | --- |
| *(stream opens)* | start of a turn | The interface creates it; the stream has no start event |
| `thought { text }` | new reasoning step | It has no id: each `thought` opens a step, following `tool_call`s attach to it |
| `tool_call { id, name, arguments }` | action of the current step | `id` links the call to its return |
| `tool_return { id, name, ok, content }` | observation of the step | Duration is measured in the interface, between call and return |
| `token { text }` | answer text | |
| `confirm_request { confirm_id, tool, risk, summary, arguments, timeout_s }` | confirmation card | Show `summary`, the **full** `arguments`, the risk level and a **countdown** of `timeout_s`; at zero, the card expires |
| `error { message }` | error message | The turn is lost; `done` follows |
| `done { reason }` | end of turn | `reason`: `final_answer`, `max_iterations` (6-step limit to explain), `error`, and `interrupted` if the extension is accepted |

The events that existed **only** in the simulated interface on 2026-10-14 (`usage`, `compression`, `artifact_patch`,
`rag_sources`, `web_results`, `guardrail`, `eval_score`, `cache_hit`, `agent_handoff`, `question`) had no
equivalent in Lot A's contract. They matched features of other lots not yet merged
(M2, M4, R2, EV1, A6, A2, X4), so they stayed simulated, and [simule-vs-reel.md](simule-vs-reel.md) said so.

*2026-10-29: the server now sends `rag_sources`, `guardrail`, `cache_hit`, `agent_handoff` (#100) and `question` (#99),
and `frontend/src/engine/wire.ts` reads them. `usage`, `compression`, `artifact_patch` and `eval_score` are still not
sent by the server.*

## 5. Gaps to close on the front end (next step on 2026-10-14)

Measured on a real stream captured from the prototype, passed through the SSE parser of the `HttpEngine` of the time:

| Sent by the server | Accepted by the interface of the time |
| --- | --- |
| `tool_call`, `tool_return`, `token`, `done`, `tool_call`, `confirm_request`, `tool_return`, `token`, `done` | `token`, `done`, `confirm_request`, `token`, `done` |

**The 4 `tool_call` and `tool_return` events were silently lost**, because `isEngineEvent` did not know them, and
`confirm_request` would have been misread (the interface expected `requestId`, `title`, `detail`; the stream sends `confirm_id`, `tool`,
`summary`, `arguments`). To do (as listed on 2026-10-14; the adapter `frontend/src/engine/wire.ts` now covers at least `tool_call`, `tool_return` and `confirm_request`, see [ADR-0035](../../decisions/0035-serveur-web-reel.md); the boxes below were not re-checked one by one):

- [ ] An adapter from Lot A's stream to the interface model (table in section 4), tested on the captured stream.
- [ ] `MockEngine` emits **Lot A's stream** events (plus marked extensions), to go through the same adapter as the real server.
- [ ] `HttpEngine`: routes `/api/sessions/{id}/...`, `Authorization: Bearer` header, session creation, `confirm_id`, branches by `fork`, interruption by `/interrupt`, and `{error, code, details}` errors.
- [ ] Confirmation card: full arguments, risk, countdown, "expired" state.
- [ ] Simulated events stay identified as such in the interface.

## 6. Evidence (2026-10-14)

- **Prototype**: `docs/conception/web_facade_spike.py` (FastAPI). Dependencies **not** declared in `requirements.txt`: `fastapi`, `uvicorn`, `httpx`.
- **15 end-to-end tests**: `tests/web/test_web_facade_spike.py`. They cover the stream and `done` last, tool ids, confirmation (accept, refuse, timeout, late answer, unknown answer, closed tab), interruption, a failing turn, unreachable Ollama, one turn per session, empty or too long message, unknown session, token, and two sessions in parallel. They are **skipped** when FastAPI is missing (CI at the time).
- **Two defects found by these tests**, fixed in the prototype: (a) an answer arriving just after the timeout refusal got `204` although it had no effect, because the confirmer expired a few milliseconds after the gateway; it now expires slightly before it (`404`, the truth); (b) an agent thread publishing after the event loop stopped raised an exception.
- **Limits**: a fake Ollama, not a real model; an in-memory session, not `SessionStore`; one machine; no load measurement; no authentication beyond a token. This is not the final server.

## 7. Questions for Lot A (2026-10-14)

1. Do you accept `done.reason = "interrupted"` and a `usage` event (ADR-0024)?
2. `tool_return.data`: do you want to carry it, or fix the sentence in `web-api.md`?
3. `confirm_id` everywhere, as proposed?
4. Does the server create the session on the first message (proposed), or through an explicit call?
5. Can a cut stream be resumed? Proposal kept: no, the turn is dropped and the client resends the message (ADR-0022).
6. Who filters the model's text (`token`, `thought`) for secrets: Lot B, or nobody (documented residual risk)?
7. Do you fix `web-api.md` (section 2), or do you want Lot D to do it in a PR?
