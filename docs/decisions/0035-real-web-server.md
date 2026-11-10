# ADR-0035 — Real web interface: `sensai-web` FastAPI server, same agent as the CLI

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-18
- **Deciders**: Ridwane (with the agreement of Christopher, Workstream D)
- **Workstream**: D (web interface); touches C (memory, RAG, cache), B (web confirmation, ADR-0015) and A (event contract)
- **Partially supersedes**: [ADR-0020](0020-simulated-web-interface.md) (the interface no longer runs only on a simulated engine); builds on [ADR-0022](0022-sse-transport-and-execution-model.md), [ADR-0023](0023-web-api-access.md) and [ADR-0024](0024-web-contract-extensions.md)

## Context
The Workstream D interface (`frontend/`) is complete, but it plays scenarios
written in advance (`MockEngine`, ADR-0020). The web server does not exist:
`src/sensai/web/` is empty, and there is only a throwaway prototype
(`docs/design/web_facade_spike.py`, 15 tests). The browser's `HttpEngine`
is a "not wired" skeleton.

What exists and must be reused as is: the agent loop and its
events (Workstream A, `to_wire`), the web confirmation (`WebConfirmationBroker`,
Workstream B, ADR-0015), sessions (`SessionStore`, M1) and all the features
on `main`: RAG with reranking (R2), cache (A6), facts (M3), `SENSAI.md`
(M4), document reading (#64), guardrails (EV2).

The transport decisions (SSE, agent in a thread), access decisions (token, local
listening) and contract extensions are already made (ADRs 0022 to 0024) and
verified by the prototype. What remains is choosing how to ship the real server.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| Keep the simulated interface | No work | Proves nothing about the integration; the team wants a real interface |
| Standard library `http.server` | No dependency | No clean async streaming, all routing and validation to write; that is what FastAPI already does |
| Flask | Familiar, simple | Synchronous: one SSE stream per turn blocks a worker, and the confirmation waits in the same process (ADR-0022) |
| **FastAPI + Uvicorn** (chosen) | What ADR-0022 and the tested prototype proposed; async streaming, input validation (pydantic), test client | Three direct dependencies (fastapi, uvicorn, and httpx for tests) and their dependencies |

**How to assemble the agent on the server side**

| Option | Pros | Cons |
| --- | --- | --- |
| Reuse the prototype's minimal agent | Simple | The web would have no RAG, no cache, no memory, no input guardrails: two different products |
| Extract the CLI assembly into a shared module | A single source | Rewrites the CLI (UI, interruption, existing tests) right before the demo: regression risk |
| **A `web/runtime.py` module that assembles the same pieces as the CLI** (chosen) | Same tools, same rules, same storage; the CLI is untouched | The assembly is written twice: a CLI change must be carried over (parity tests detect it) |

## Decision
1. **`sensai-web`** starts a FastAPI server on `127.0.0.1` (ADR-0023). It
   generates a random token, prints it once in the console, and also serves
   the built interface (`frontend/dist`): same origin, so no
   CORS by default. The CLI options (`--model`, `--host`, `--no-rag`…)
   apply.
2. **Same agent as the CLI**: the shared registry, project
   search, `update_state`, `save_fact` and `recall_facts`, the gateway with
   the guardrails, the input filter, the semantic cache, and sessions
   saved in `~/.sensai/sessions.db`. A web session is a CLI
   session: it can be resumed from either side.
3. **The stream** is Workstream A's (`to_wire`: `token`, `thought`,
   `tool_call`, `tool_return`, `error`, `done`), plus the ADR-0024 extensions
   the server can produce without touching the core:
   `done.reason = "interrupted"`, `confirm_request` (Workstream B broker),
   `rag_sources`, `cache_hit` and `guardrail` (blocked input).
4. **The browser translates** this stream into the interface's display model,
   in a single adapter (`frontend/src/engine/wire.ts`).
5. **The routes** follow `web-api.md`, with the corrections noted in
   `web-api-alignment.md` (`confirm_id`): sessions (create, list, read),
   message (SSE stream), confirmation, interruption, fork (`fork` = a
   new session), secret-filtered export, health, configuration without
   address or path, profile, facts and state document (read-only).
6. **At startup**, sessions that are too old are purged as in the
   CLI (`--retention-days`): this is issue #65.
7. **What remains simulated**, and is shown as such: token consumption
   (`usage`), compression, evaluation scores, handoffs between
   agents, form-based questions (`ask_user`), personas and the share
   link. Without a reachable server, the interface falls back to demo mode.

## Consequences
- ✅ A real interface: every response comes from the real agent, with the same tools, memories and guardrails as the CLI.
- ✅ Sessions are shared between the CLI and the web.
- ✅ A single command (`sensai-web`) serves the API and the interface: no CORS, no second server.
- ❌ The agent assembly exists in two copies (CLI and web); parity tests watch it, but an omission remains possible.
- ❌ Three more dependencies (FastAPI, Uvicorn, httpx in dev), with their dependencies (starlette, pydantic, anyio…).
- ❌ A single user at a time per token, on the local machine: no accounts, no remote access without an explicit option.
- ❌ Several interface pages (agents, quality, prompts, scheduling) remain demos.
- Follow-up: API and stream tests (`tests/web/`), adapter tests (`frontend/tests/`), trial run on the pod in a browser. Revisit sharing the assembly with the CLI after the demo.
