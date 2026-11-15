# ADR-0037 - Multi-Agent Orchestration: delegation through a tool (`delegate_task`)

- **Status**: Partially superseded by [ADR-0038](0038-specialized-agents-and-handoffs.md) (roles, handoffs, depth 1, sub-agent deadline)
- **Date**: 2026-10-24
- **Deciders**: Fresnel (Workstream A)
- **Workstream**: A (`core/`, `tools/`)

## Context

[A2] Multi-Agent Orchestration requires the agent to be able to break a
complex task into subtasks and hand them to sub-agents, rather than
doing everything in a single linear reasoning turn.

Repo constraints: no multi-agent framework, everything goes through Ollama's
HTTP API (like the rest of the project); sub-agents must respect
the same guardrails and confirmations as the main agent (A3, EV2,
ADR-0006) - a sub-agent is not a way around the gateway.

## Considered options

| Option | Pros | Cons |
| --- | --- | --- |
| New "orchestrator" driving several ReAct loops from outside (new entry point, new CLI) | Clean separation between simple mode and multi-agent mode | A second path to maintain alongside `cli.py`; the user must know which to choose before starting; guardrails would have to be rewired by hand. |
| Delegation as a **tool** (`delegate_task`) offered to the existing agent | Nothing new on the interface side: the agent itself decides, during a normal conversation, when to delegate. Reuses `run_agent_turn` (ADR already in place) and the SAME gateway (ADR-0006): permissions, guardrails and confirmations apply identically to the tools the sub-agent calls. | The sub-agent can, through the same tool, delegate in turn: an explicit depth limit is needed to avoid endless recursion. |
| Parallel sub-agents (threads/async) for several subtasks at once | Faster on independent subtasks | A3 confirmation is interactive (terminal): two sub-agents asking for confirmation at the same time cannot be cleanly untangled in the CLI. Complexity to keep for a later iteration if the need is measured. |

## Decision

Delegation is a tool, `delegate_task(task, persona?)`, registered
in the same registry as the other tools (`tools/delegate_tool.py`). It
runs a sub-agent **sequentially** via `run_agent_turn`
(`core/agent.py`), with:
- an isolated history (the sub-agent does not see the current conversation -
  the subtask must be self-explanatory);
- the **same gateway** (`ToolGateway`) as the main agent: the same
  permissions, the same input/output guardrails, and the same confirmation
  before a risky action (EV2, A3);
- a bounded delegation depth (`MAX_DELEGATION_DEPTH = 2`, tracked by
  a `contextvars.ContextVar`): a sub-agent can delegate itself, but
  not indefinitely.

Declared risk `execute` (the worst case): it is not the tool itself that
is dangerous, but it opens the door to any tool the
sub-agent chooses to call, so it must never be loosened by a
permissive user preference (`tool_policy.LOOSENABLE` already excludes it
for `execute`).

Wired only into the CLI chat (`cli.py`), after the gateway is built -
not in `registry.py` (shared with the X5 scheduler),
because the tool needs a reference to its own gateway, which
`build_registry()` does not build.

## Consequences

- ✅ No new dependency, no new entry point: the model
  decides itself, in a normal conversation, when to break down a
  task.
- ✅ Sub-agents inherit all existing guardrails (A3, EV2) without
  duplicated code: they go through the same gateway.
- ❌ Strictly sequential execution: delegating three independent
  subtasks is no faster than a ReAct loop doing them one
  after the other itself - only the split of the reasoning changes, not the
  latency. Parallelism is explicitly ruled out above, not forgotten.
- ❌ Not wired into `sensai-schedule` (X5) nor into the web interface (Workstream D,
  `src/sensai/web/runtime.py`): both entry points also build a
  gateway, but `delegate_task` is not registered there. To do if the
  need is confirmed, without rewriting this ADR.
- Follow-up: if truly independent, slow subtasks become
  common (measured, not assumed), re-evaluate parallel execution at
  that point.
