# ADR-0038 — Multi-Agent Orchestration: specialized agents and handoffs

- **Status**: Accepted (2026-10-24)
- **Date**: 2026-10-24
- **Deciders**: Ridwane (Workstream C) and Fresnel (Workstream A)
- **Workstream**: A (`tools/`, `prompts/`); affects D (`web/runtime.py`)
  and Meric's tool execution (`execution/gateway.py`)

## Context

[ADR-0037](0037-sub-agent-delegation-tool.md) shipped `delegate_task`:
the main agent launches a generic sub-agent. Compared with the catalog
text, that is not enough for A2:

> *Multi-agent orchestration has several **specialized** agents coordinate on
> a task, **passing work between them**.* (examples: researcher, writer and
> critic in CrewAI; debating agents in AutoGen; LLM router)

All sub-agents were identical (same prompt, same tools) and
none received another's work. Trial runs on the pod
(`qwen3-coder:30b`, details in
[`docs/performance/A2-orchestration.md`](../performance/A2-orchestration.md))
also revealed five defects in the ADR-0037 version:

| Measured defect | Figure |
| --- | --- |
| The sub-agent ignores the project prompt (profile, facts) | saved fact retrieved 1 time in 3 without it, 3 in 3 with it |
| Depth 2 loops endlessly | 120 s for an empty answer (3 re-delegations) |
| The sub-agent keeps going after the gateway gives up | 20 s of ghost work; a write requested 14 s after giving up |
| The agent never delegates on its own (description only) | 0 delegations out of 10 requests |
| The reviewer takes the developer at their word | wrong work approved 6 times out of 6, without opening the file |

## Considered options

| Option | Pros | Cons |
| --- | --- | --- |
| Keep only the generic `delegate_task` (ADR-0037) | Nothing to add | Does not match the requirements: neither specialization nor handoff |
| A multi-agent framework (CrewAI, AutoGen, LangGraph) | Ready-made roles and handoffs | Forbidden by the project (no LLM framework, Ollama HTTP API only); would bypass the ADR-0006 gateway |
| Roles in `delegate_task` + a fixed `team_task` chain (explorer → developer → reviewer, at most one fix round) | Reuses the ReAct loop and the same gateway; each role only sees its tools; deterministic chain, so testable without a model | Fixed chain (no free debate); slower than a single agent; everything must fit within one tool's timeout |
| Agents debating freely (AutoGen style) | More flexible | Unpredictable number of turns, hard to bound within 120 s, nested A3 confirmations |
| Model router (small model for simple requests) | Lower cost and latency | Requires a second model loaded on the pod (GPU memory): not measured, postponed |

## Decision

1. **Specialized agents**: `delegate_task` takes a `role` among
   `explorateur` (explorer: reads and searches), `developpeur` (developer: can write and execute,
   with confirmation) and `relecteur` (reviewer: reads and judges). Each role has its own
   instructions and **only sees its tools**; an out-of-role call is refused
   without being executed.
2. **Handoffs**: `team_task` chains explorer → developer →
   reviewer; each agent receives the previous one's work. The reviewer
   receives the **exact content written** by the developer (captured from
   `write_file` calls), not just its report. If it returns a
   "needs fixing" verdict, the work goes back once to the developer. Each handoff
   is shown in the terminal.
3. **Fixes to ADR-0037**:
   - the sub-agent receives the project prompt;
   - it does not re-delegate (`MAX_DELEGATION_DEPTH = 1`, delegation tools
     hidden);
   - it stops at its deadline (120 s minus a 30 s margin): no more tools or
     confirmations after that, partial answer returned, generator closed;
   - the gateway copies the context into the tool's thread
     (`contextvars.copy_context()`), otherwise the depth restarted from 0.
4. **When to use it**: rules in the `v2` system prompt (A4 registry):
   delegate from three files upward, hand code changes to
   the team, answer a question yourself.

The model router is not adopted for now (see Follow-up).

## Consequences

- ✅ A2 matches the requirements text: three specialized agents handing
  work to each other, with a critic that can send it back to the developer.
- ✅ No new dependency; same guardrails and confirmations for all
  agents (ADR-0006, A3, EV2); a read-only role cannot
  write, even if the model tries.
- ✅ Deterministic chain: tested without a model (`tests/tools/test_team_tool.py`).
- ❌ Slower: a change by the team takes several times as long as
  the single agent (figures in the measurements document). We pay for
  verification.
- ❌ Up to the model, not guaranteed: the `v2` prompt rules are followed
  in most trials, not all (see the measurements document).
- ❌ The whole chain fits within a single tool's timeout (120 s by default):
  a long task stops before the end, and says so.
- ❌ The reviewer only judges what the developer wrote with
  `write_file`; a change made another way (through `run_code`) is not
  shown to it.
- Follow-up: measure a model router if a second model fits on the pod;
  revisit the timeout if team tasks often exceed 90 s. If this ADR
  is accepted, ADR-0037 moves to the status "Partially superseded by
  ADR-0038" (only its status line changes).
