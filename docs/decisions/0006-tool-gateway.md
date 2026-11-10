# ADR-0006 — A gateway enforces permissions, validation and confirmation on every tool

Date: 2026-10-07
Workstream: B (impacts A, C, D)
Status: accepted — approved by Workstream A (2026-10-11): the ReAct loop calls tools through the gateway

## Context
[ADR-0002](0002-shared-tool-registry.md) provides a common contract (`Tool`)
and a registry. It says nothing about what must happen *around* the call:
who may call what, who validates arguments and results, when the user is
asked. Without a common rule, each tool (sandbox, RAG, MCP, files, web
search) would reinvent these checks — or forget them. And ADR-0005 points
out that exposing the agent on the web means exposing code execution: these
checks are the only barrier.

## Considered options
- **Each tool does its own checks** — rejected: A3 and EV2 would have to be
  wired N times, and tool N+1 would forget them without anything flagging
  it.
- **Extend `ToolRegistry.call` in `core/tools.py`** — rejected for now: a
  Workstream A file, where any change affects all four workstreams. May
  become the next step if Workstream A agrees.
- **A `ToolGateway` wrapping the registry** (`execution/gateway.py`) —
  chosen: the registry and the `Tool` protocol do not change, an existing
  tool keeps working.

## Decision
1. The agent calls `ToolGateway.call(name, **kwargs)` (same signature as
   `ToolRegistry.call`), never the registry directly.
2. Each tool declares a `risk` (`read`, `network`, `write`, `execute`). A
   tool that does not declare one is treated as `execute`.
3. The mode (`allow` / `ask` / `deny`) follows from the risk; user
   preferences can always **tighten** it, but only **relax** `read` and
   `network`. `write` and `execute` always require confirmation.
4. Arguments and results are validated; the EV2 guardrails plug into two
   points (input, output); the A3 confirmation is supplied by the interface
   (ADR-0005, point 3).
5. Any failure of a guardrail, a filter or a confirmation **blocks** rather
   than letting the call through. Tool calls and confirmations have a
   timeout enforced by the gateway; tool failures are classified
   (`timeout`, `network_error`, `tool_error`) so the model knows whether it
   can retry.
6. Gateway decisions go back to the model as a `ToolResult` (`ok=False`,
   `data["error"]` = stable code), so the agent adapts to a refusal instead
   of crashing.

## Consequences
- Adding a tool = declaring its risk and returning a `ToolResult` (see
  `docs/architecture/tool-contract.md`). The checks apply to it without the
  tool writing them.
- A3, EV2 and web confirmation each have a single hook point.
- **Nothing yet prevents the agent from calling `registry.call` directly.**
  As long as the ReAct loop (Workstream A) does not use the gateway, the
  protection is not effective: this must be wired with Workstream A, and a
  test must guarantee that the agent does not hold the raw registry.
- An exceeded timeout does not stop the tool (a thread cannot be killed).
  Tools that modify state must bound their own duration.
- The floor on `write`/`execute` makes an "always allowed" tool impossible
  without changing the code: intended, but to be accepted if we want a
  smooth demo.
- External tools (MCP) must declare a risk on registration; an unknown MCP
  server will therefore be treated as `execute`.
