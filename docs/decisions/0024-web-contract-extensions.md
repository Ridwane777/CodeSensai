# ADR-0024 — Extensions to Workstream A's contract: what we ask for, and what to do if refused

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Christopher (Workstream D), to be approved by Fresnel (Workstream A)
- **Workstream**: D (affects A for three additions to the core)

## Context
Written **after** the user stories [US-WEB-6 to 12, 16](../architecture/web-api.md). Features X2 (interruption,
forking), X3 (export, share), X4 (questions), EV3 (log) and M1 (profile) need behaviors that
Workstream A's contract does not describe (section 3 of [web-api-alignment.md](../architecture/web/web-api-alignment.md)). Without an explicit decision,
the interface would silently simulate them, or each workstream would invent its own version.

Principle: [ADR-0005](0005-web-interface-facade.md) allows completing `core/` when something is missing, but
any addition to the core is a request to Workstream A and an effect on the CLI. So we touch it **only for what cannot be
done elsewhere**.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| Put everything in the core | A single place, the CLI benefits | Seven requests to Workstream A, some unrelated to the core (export, share) |
| Put everything in the web server | No request to Workstream A | Impossible: an interruption or token usage are only known in the core |
| **Minimum in the core, the rest in the server, with a fallback for each extension** | Depends on Workstream A only where unavoidable; each story stays verifiable if a request is refused | More API surface to secure and test |

## Decision
**Three requests to the core (Workstream A):**
1. `Done.reason` accepts `"interrupted"`; the server exposes `POST /interrupt`.
2. A `usage` event (`prompt_tokens`, `completion_tokens`, `duration_ms`), read from the last chunk of Ollama's response.
3. `ToolReturn.data` (optional) carries `ToolResult.data` (sources, traceback, file diffs).

**Five additions to the server, without touching the core:**
4. **Fork = new session**: `POST /fork {"at_message": n}` copies the history up to message `n`. A branch is an ordinary session.
5. **Question = tool**: the agent asks through an `ask_user` tool (risk `read`); the server emits `question` and waits for `POST /answer`, as for confirmation. The core does not know about the interface.
6. **Export**: `GET /export?format=json|md`, filtered of secrets; PDF stays on the browser side.
7. **Share**: see [ADR-0023](0023-web-api-access.md).
8. **Profile, configuration, health**: simple routes over the existing `Profile` and configuration.

**Fallback if a request is refused** (each story describes it): the interface drops its connection to interrupt; estimates usage while flagging it as estimated; shows only the tools' `content`; keeps branches in page memory.

## Consequences
- ✅ Only three requests touch the core, and each is justified by a story.
- ✅ Each extension has a fallback: the demo stays honest if Workstream A refuses.
- ❌ **Depends on Workstream A's time and agreement**, while delivery is approaching; without an answer, the interface keeps simulated behaviors for X2, X4 and EV3.
- ❌ **More surface to secure**: each added route is one more door (token, validation, filtering).
- ❌ **A branch that is a session** clutters the session list, and a fork copies the history (proportional memory and disk cost).
- ❌ **`ask_user` requires the model to know when to ask**: if the model does not use it, the form never shows, whatever the interface does. To be measured, not assumed.
- Follow-up: Workstream A's answers to questions 1 to 3 of [web-api-alignment.md](../architecture/web/web-api-alignment.md); update `docs/architecture/web/simulated-vs-real.md` for each wired extension. **Revision threshold**: if Workstream A refuses the three core requests, replace this plan with the fallbacks and say so in the demo.
