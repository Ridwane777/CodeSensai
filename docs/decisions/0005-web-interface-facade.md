# ADR-0005 - The web interface is a facade, not a second agent

Date: 2026-09-25
Workstream: D (impacts A and B)
Status: Accepted (2026-11-01, approved by the team)

## Context
The team grows from three to four: Christopher joins the project, specialized
in web and interfaces. Two organizational consequences, recorded in the
README:

- the web interface (`[X1]`) leaves Workstream C, which held the RAG *and*
  session memory *and* the frontend;
- the MCP tool (`[T1]`) leaves Workstream A, where it was filed without
  being started.

The underlying question remains: what is the web interface allowed to do?
The default answer - "it reimplements whatever it needs" - produces two
agents that diverge, and a demo where the CLI and the browser give different
answers to the same question.

## Considered options
- **A standalone web backend** that reimplements the agent loop to be free in
  its choices (streaming, message format, error handling). Rejected: the
  reasoning logic would exist in two places, and every Workstream A fix
  would have to be ported by hand.
- **A facade**: the web exposes over HTTP what the CLI exposes in the
  terminal, on top of the same `sensai.core`. Chosen.

## Decision
1. **The web calls `sensai.core`, it does not duplicate it.** All reasoning,
   tool-calling and history logic stays in `core/`. If the web needs a
   behavior `core/` cannot provide, we change `core/` - and the CLI benefits
   too.
2. **The exchange format between the interface and the core is frozen
   before development**, just as the `Tool` protocol was for tools
   (ADR-0002). Until it is written, Workstream D cannot progress in
   parallel. This is Christopher's first task, together with Workstream A.
3. **The way to ask the user a question is supplied by the interface.**
   `execution/human_in_loop.confirm()` must not call `input()`: the CLI
   supplies its console version, the web supplies a button. Without this,
   confirmation before a risky action (`[A3]`) is unusable from a browser.
4. **The trace of agent turns (`observability/`) belongs to the same
   workstream as the interface.** It is the same data, produced then
   displayed.

## Consequences
- Christopher can develop against a fake backend as soon as point 2 is
  written, without waiting for the ReAct loop to be finished.
- Point 3 is a change in a Workstream B file: to be announced to Meric; it
  is not a fix but a new constraint that comes with a second interface.
- **Exposing the agent on the web means exposing code execution on the
  web.** A page reachable without authentication lets anyone run Python on
  the host machine. The sandbox (`[T2]`), the guardrails (`[EV2]`) and human
  confirmation (`[A3]`) stop being a comfort: they become the only barrier.
  To be handled when designing the API, not afterwards.
- Same remark for the remote Ollama pod in
  [ADR-0004](0004-model-and-infrastructure.md): an instance open to the
  Internet is a generation API open to everyone. Closing that access is part
  of Workstream D's scope.
- FastAPI (or equivalent) is allowed: it is a web framework, not an LLM
  framework - [ADR-0001](0001-no-llm-framework.md) is not affected.
