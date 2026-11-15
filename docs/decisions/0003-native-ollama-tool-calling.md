# ADR-0003 - Native Ollama tool calling rather than parsing ReAct text

Date: 2026-09-22
Workstream: A (impacts B and C)
Status: Accepted (2026-11-01, approved by the team)

## Context
The ReAct loop (`core/agent.py`) must decide, on each turn, whether the model
calls a tool or answers. Two ways to retrieve that decision:

1. ask the model to write `Action: tool_name(arguments)` as text, and parse
   that line ourselves (what `prompts/react_prompt.txt` describes);
2. pass the tool list in the `tools` field of `POST /api/chat` and read the
   `message.tool_calls` field of the response, already structured by Ollama.

The requirements forbid LLM frameworks, not features of the Ollama API
itself: both options remain raw HTTP via `core/ollama_client.py`, so they
comply with [ADR-0001](0001-no-llm-framework.md).

## Considered options

- **Text parsing** - a single format to master, works with any model. But
  with a small local model like `qwen3:8b`, the output drifts: missing
  quotes, half-closed argument JSON, `Action:` in the middle of a sentence,
  two actions in the same turn. Each case gets patched in the parser, and
  those patches are exactly the kind of code we can no longer test or
  explain in a review.
- **Native `tools` field** - Ollama returns `tool_calls` with the tool name
  and its arguments already deserialized. Our tools' `parameters` schemas
  (`core/tools.py`) are already in the expected JSON Schema format: nothing
  to rewrite on the Workstream B and C side. Constraint: the chosen model
  must support tool calling (`qwen3:8b` and `mistral` do, not all models do).

## Decision
The agent sends `registry.describe_all()` in the `tools` field of the Ollama
request and reads tool calls from `message.tool_calls`. The
Thought/Action/Observation cycle remains visible to the user - that is the
reasoning-transparency requirement - but **the executed decision comes from
the structured field, never from the displayed text**. Text parsing is kept
only as a fallback if the configured model returns no `tool_calls`.

## Consequences
- No more fragile parser to maintain in `core/agent.py`; the loop boils down
  to: call, read `tool_calls`, `registry.call(...)`, feed the observation
  back as a `role: "tool"` message, loop until `MAX_ITERATIONS`.
- Workstreams B and C change nothing: the `Tool` contract is already the
  right format.
- Model choice becomes constrained (it must support tool calling). To be
  documented in the README, and checked at startup rather than letting the
  agent fail silently mid-session.
- Streaming gets more complicated: a response containing a tool call does
  not stream word by word like a final answer. The loop streams the text of
  final answers, and displays actions as steps.
