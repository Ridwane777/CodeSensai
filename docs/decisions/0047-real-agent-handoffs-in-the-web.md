# ADR-0047 - Web interface (X1, A2): real `agent_handoff` events, announced when a sub-agent actually starts

- **Status**: Accepted (2026-11-01, validated by the team)
- **Date**: 2026-10-29
- **Deciders**: Ridwane (Lot C), on behalf of Lot D (Christopher) - to be confirmed by the team
- **Lot concerned**: D (`web/runtime.py`, `frontend/`), with a small hook in A's `tools/team_tool.py` (Fresnel)

## Context

The web contract has an `agent_handoff` event since the simulated interface
([ADR-0020](0020-simulated-web-interface.md)): the conversation and the Agents
page show "CodeSensai → Relecteur". Multi-agent work became real in the agent
([ADR-0037](0037-sub-agent-delegation-tool.md), [ADR-0038](0038-specialized-agents-and-handoffs.md):
`delegate_task` with roles, `team_task` explorer → developer → reviewer), and
both tools are registered in the web server, but the server never told the
browser who had control. The relays only existed in the simulated scenarios
(issue #32). In the terminal, `TeamTool` already prints each relay through a
`notify(str)` callback.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| **Server-side events, announced when the sub-agent starts** (chosen) | The relay is shown only if it really happens: a delegation refused at the confirmation shows nothing; the order is right (confirmation, relay, result) | Needs a structured hook in `TeamTool` (Lot A) and a small `DelegateTool` subclass in the web runtime |
| Derive the relays in the browser from `tool_call` / `tool_return` of `delegate_task` | No server change | Shows a relay for a delegation the user then refuses; cannot see the inner relays of `team_task` (one tool call for three agents) |
| Parse the `notify` strings of `TeamTool` | No change to Lot A | Couples the web to French log messages; breaks silently if the wording changes |

## Decision

- `TeamTool` gets an optional `on_handoff(role)` callback, called when each
  role takes over (next to the existing `notify`).
- The web runtime tracks who has control during a turn (`Handoffs`) and emits
  `{"type": "agent_handoff", "from", "to"}`, with `"main"` for the main agent:
  when a `delegate_task` sub-agent starts (its role, or `"sous-agent"`), at
  each `team_task` relay, and back to `"main"` just before the `tool_return`
  of either tool.
- The frontend (`engine/wire.ts`) replaces `"main"` with the persona shown and
  marks these events `subAgent`: the store shows the relay without changing the
  agent chosen in the selector.
- Tools from an MCP server (`mcp_<server>_<tool>`, ADR-0041) get an "MCP" badge
  in the reasoning ribbon; they were already real tool calls, only unmarked.

## Consequences

- ✅ The relays seen in the web are the ones that happened, in order, including
  the reviewer sending work back to the developer.
- ✅ No change to the agent loop or the event types of the core.
- ❌ What the sub-agents do inside their turn (their own tool calls) is still not
  streamed: the user sees who works, not each step of the sub-agent.
- ❌ The CLI keeps its text messages; the two interfaces show the same relays
  through two different hooks (`notify` and `on_handoff`).
- ❌ The "Agent actif" selector still only changes the displayed name: the web
  server does not read the personas (A5, [ADR-0042](0042-configurable-personas.md)).
- Follow-up: stream the sub-agents' steps if the demo needs it.
