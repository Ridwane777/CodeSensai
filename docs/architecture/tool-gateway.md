# Technical requirements — Tool gateway (contract shared by every tool)

> Moved from `docs/user-stories/` on 2026-11-02: these are technical requirements shared by the features, not user stories of one catalogue feature.

Workstream B — Hands (Meric). `execution/gateway.py`, `tool_validation.py`,
`tool_policy.py`. Contract: [tool-contract.md](../architecture/tool-contract.md);
decision: [ADR-0006](../decisions/0006-tool-gateway.md).
Not a catalogue feature: it is the base that makes A3, EV2 and T2/T4
apply to **every** tool, including those of the other workstreams.

Personas: Marc, the lead who configures the tool for the team, and Camille,
the developer ([persona-and-scenario.md](../design/persona-and-scenario.md)).

---

## US-GW-1 — Add a tool without rewriting the security

**As** Marc, the lead who adds an in-house tool (a search, an MCP server…) for the team,
**I want** to declare only a name, a schema, a risk and a `run` function,
**so that** confirmation, masking, validation and limits apply without my coding them.

**Acceptance criteria:**
- Every call follows the same sequence: known tool, enabled, valid arguments, permission mode, input guardrails, confirmation, execution, valid result, output filters, size limit.
- An unknown tool name, a disabled tool or a user refusal returns an error result readable by the model, never an exception.

## US-GW-2 — A model that makes a mistake does not crash the agent

**As** Camille, the developer whose local model sometimes produces malformed calls,
**I want** the arguments to be validated against the tool's schema before execution,
**so that** the error goes back to the model for it to correct itself, instead of crashing the tool.

**Acceptance criteria:**
- A missing argument, a wrong type, a value outside the `enum` or an unknown argument is refused with the faulty field named.
- A tool that exceeds its maximum duration is stopped and reported; a result that does not follow the contract is refused.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-GW-1 | ✅ | `execution/gateway.py` | `tests/execution/test_gateway.py` (`unknown_tool`, `disabled_tool_is_not_run_and_not_offered`, `refusal_is_a_result_the_agent_can_read`) |  |
| US-GW-2 | ✅ | `execution/tool_validation.py`, `execution/gateway.py` | `tests/execution/test_tool_validation.py`, `tests/execution/test_gateway.py::test_invalid_arguments_are_rejected_before_running` |  |
