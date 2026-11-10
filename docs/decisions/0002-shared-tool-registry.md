# ADR-0002 — A shared tool registry rather than direct calls

Date: 2026-09-21
Workstream: A (impacts B and C)
Status: accepted

## Context
Three features (sandbox, RAG, external MCP tool) must all be callable by the
agent. They are developed by 3 different people in parallel, on very
different subsystems (code execution, semantic search, external network
call).

## Considered options
- The agent imports and calls `execution.sandbox` and `knowledge.rag`
  directly — rejected: tightly couples Workstream A to the implementation
  details of Workstreams B and C; impossible to test the ReAct loop before
  sandbox and RAG are done.
- A common `Tool` contract (name/description/parameters/run) + a central
  `ToolRegistry` — chosen.

## Decision
Every capability exposed to the agent implements the `Tool` protocol
(`core/tools.py`) and registers itself in a `ToolRegistry`. The agent only
interacts with the registry, never with a concrete implementation.

## Consequences
- The 3 workstreams can develop and test their module in isolation from the
  start (Workstream A tests its loop against `EchoTool` while waiting for
  sandbox and RAG).
- Integration becomes: register your tool in the registry — not a rewrite
  of the agent for every new feature.
- Small upfront cost (writing the protocol, the wrapper per tool) — paid
  back as soon as 2 or more tools exist.
