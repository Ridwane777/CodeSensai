# ADR-0031 - Tool calls written as text: parse them only when the response is nothing else

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-17
- **Deciders**: Ridwane (Workstream C), to be approved by Fresnel (Workstream A, `core/agent.py`)
- **Workstream**: A (`core/agent.py`); complements [ADR-0003](0003-native-ollama-tool-calling.md) without superseding it

## Context
ADR-0003 routes tool calls through Ollama's structured
`tool_calls` field: "never displayed text". During the M3 trial runs
(RunPod pod, `qwen3-coder:30b`, Ollama 0.40.6, 2026-10-17), the model
often writes its call in the text, in its own format
(`<function=…><parameter=…>…</parameter></function>`), without the opening
`<tool_call>` tag: Ollama does not recognize it, nothing is executed.

Measurements (structured calls, 8 tools offered, same system prompt):
- `read_file`, `run_code`, `web_search`, `search_codebase`, `recall_facts`,
  `update_state`: 5 or 6 out of 6 once descriptions were shortened;
- `save_fact` ("remember that…"): 1 out of 6, and 4 out of 12 under the name
  `remember_fact`. With a single tool offered: 8 out of 8. It is not our
  prompt: without it, the rate is the same.

Worse than the failure: before any fix, the model then claimed to have
done the action ("the version was changed from 7 to 8") when nothing had
been executed.

## Considered options

| Option | Pros | Cons |
| --- | --- | --- |
| Never parse text; re-prompt the model, then stop with a clear error | Strict application of ADR-0003 | Measured: 2 saves out of 5 in the CLI; M3 unusable in a demo for remembering a fact |
| **Parse calls in qwen3-coder's native format, only when the response is nothing else, then route them through the normal path** (chosen) | It is the model's own call syntax, not free text to interpret; the call then goes through the gateway, the guardrails and the confirmation like a structured call | Depends on one model's format: another model will have its own; an injected response consisting only of a call would be parsed |
| Switch models | Possibly more reliable | Contradicts ADR-0004 two weeks before delivery, with no guarantee |
| Parse ReAct-style formats (`Action: …`) | Works with any model | Exactly what ADR-0003 ruled out: free, ambiguous text |

## Decision
In `core/agent.py`, when the model responds without a structured call:
1. if the response **consists only** of calls in the format
   `<function=name><parameter=key>value</parameter>…</function>` (with or without
   `<tool_call>`), and each `name` is a tool **offered** to the model,
   those calls are parsed and follow the normal path: gateway, permissions,
   guardrails, **confirmation** for writes and execution. Values
   are converted according to the tool schema (integer, number, boolean),
   otherwise left as text. A `Thought` reports it;
2. if the response mixes text and a call, contains a malformed call or
   targets a tool that was not offered, **nothing is executed**: the same request is
   asked again, without its failed response (sending it back encourages the model to
   copy it), at most twice, then the turn stops with an `Error`.

## Consequences
- ✅ Calls the model intended but Ollama did not recognize are
  made, with no exception to the gateway or the confirmation.
- ✅ The model can no longer claim an action that did not happen: either
  the call is made, or the turn stops with a visible error.
- ❌ Departure from the letter of ADR-0003: a response consisting only of a
  call written as text is executed. An injection that made the
  model respond *only* with a call would be parsed; it would still go through
  confirmation for any write or execution, but not for a read.
- ❌ Tied to qwen3-coder's format: another model will need its own
  parser, or nothing (the structured field remains the normal path).
- ❌ A retry costs one more model call (a few seconds).
- Follow-up: `core/agent.py` tests (lone call parsed, confirmation and refusal
  applied, schema types, multiple calls, non-offered tool refused,
  call mixed with text never executed); measurement in the real CLI
  ([M3 trial run](../performance/M3-facts.md)). Revisit if an Ollama version
  recognizes these calls.
