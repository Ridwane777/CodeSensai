# ADR-0020 — Web interface built on a simulated engine, behind a replaceable contract

- **Status**: Accepted (2026-11-01, approved by the team); partly superseded by [ADR-0035](0035-real-web-server.md) (real server)
- **Date**: 2026-10-13
- **Deciders**: Christopher (Workstream D)
- **Workstream**: D (affects A for the event contract, and all workstreams for the demo)

## Context
For the mid-project demo, the complete user journey of CodeSensai must be
shown. But the web backend does not exist: `src/sensai/web/` and
`src/sensai/observability/` are empty, the ReAct loop (A1) only has its contract,
and the sandbox, guardrails, confirmation and MCP tool are
skeletons. Waiting for the backend would block all interface design.

[ADR-0005](0005-web-interface-facade.md) already requires the interface to be a
facade over `sensai.core` and the exchange format to be frozen before
development. What remains is choosing how to move forward without a backend.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| Static pages with hard-coded answers | Very fast | Throwaway, no credible reactivity (interruption, confirmation, form), to be redone entirely. |
| Fake FastAPI backend replaying scenarios | Closer to reality, tests the network | Two work streams for one demo; one more server that can fail on demo day. |
| **React interface wired to an `Engine` interface, with a `MockEngine` in the browser** | A single interface for the mid-project demo and the final delivery; the real backend only replaces the adapter; demo with no network or server; the event contract is written and tested right away | The contract is a proposal until Workstream A approves it; the demo does not prove the real integration. |

## Decision
The interface is developed in `frontend/` (React, Vite, TypeScript, Tailwind)
against an `Engine` interface and a stream of typed events
(`frontend/src/contract/`). A `MockEngine` plays scripted but
reactive scenarios. An `HttpEngine` (skeleton, not wired) carries the future SSE stream to
FastAPI. Every screen shows a "Simulated engine" badge.

## Consequences
- ✅ Interface design and demo progress without waiting for A, B and C.
- ✅ The interface ⇄ engine contract is written, typed and tested (`frontend/tests/`): it serves as a basis for discussion with Workstream A.
- ✅ Demo with no network: no possible server-side failure on demo day.
- ❌ **The demo does not prove that the real engine can produce these events**: integration remains to be done and may reveal gaps (formats, latencies, event order).
- ❌ The contract is proposed by Workstream D alone: if it diverges from what Workstream A can emit, it will need revising (new ADR if the decision changes).
- ❌ Perception risk: a scripted demo can be mistaken for a real agent. Mitigation: permanent badge, page [simulated-vs-real.md](../architecture/web/simulated-vs-real.md), and an explicit statement during the presentation.
- ❌ Keyword routing does not understand free language: any phrasing outside a scenario gets a fallback answer.
- Follow-up: validate the contract with Workstream A; list the gaps in `simulated-vs-real.md` for each screen wired to the real engine. **Revision threshold**: if at final delivery the real engine emits different events, replace this contract with a new ADR.
