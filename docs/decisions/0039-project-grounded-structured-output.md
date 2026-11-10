# ADR-0039 — Structured output (T5) in two steps: search, then format

- **Status**: Accepted (2026-10-24)
- **Date**: 2026-10-24
- **Deciders**: Ridwane (Workstream C) and Fresnel (Workstream A)
- **Workstream**: A (`core/structured.py`); the CLI (`cli.py`)

## Context

[ADR-0036](0036-structured-output-json-schema-format.md) makes `/structured`
a single model call with Ollama's `format` field, **without tools**
(`format` and `tools` cannot be combined in one call). The shape is
guaranteed, the substance is not: the model can neither read a file nor
search the project, it answers from memory.

Full trial run on the pod (2026-10-24): "the list of functions in
stats.py" returned five invented functions (`moyenne`, `median`, `mode`…)
for a file that defines only one (`maximum`). Dedicated measurement
(`scripts/bench_t5.py`): **0 correct answers out of 15**.

## Considered options

| Option | Pros | Cons |
| --- | --- | --- |
| Keep the direct call and document the limit | Nothing to change, a single request | A well-formed but wrong JSON answer on any question about the project: 0 out of 15 |
| Attach the files named in the request to the prompt | At most one more request, deterministic | Only works if the request names the file; nothing for "where is…" or "which routes…" |
| **Two steps: the agent searches (ReAct loop, tools, same gateway), then the constrained call formats its answer** | All the agent's capabilities (reading, search, facts); keeps the ADR-0036 constrained call as is; measured 15 out of 15 | Slower (3.7 to 15.8 s versus 0.9 to 3.9 s); gateway confirmations may be requested during `/structured` |

## Decision

In the CLI, `/structured <schema> <request>` first runs an agent
turn (project system prompt, tools, same gateway: same
guardrails and confirmations), displayed like a normal turn. Its answer is
then given to the constrained call (`format`), with the instruction to fill
the schema only from what the agent found. Without `gather` (programmatic
call), the ADR-0036 behavior remains available.

ADR-0036 is not superseded: the constrained call remains the one it describes;
this ADR adds the search step that precedes it.

## Consequences

- ✅ Answers are about the real project: 15 out of 15 correct versus 0 out of
  15 (details in [T5-structured.md](../performance/T5-structured.md)).
- ✅ No new dependency; the constrained call and its shape guarantees
  do not change.
- ❌ Two to four times slower: there is an agent turn before
  formatting.
- ❌ Formatting copies what the agent wrote: if the agent is wrong,
  the JSON is wrong too (the right schema does not fix wrong substance).
- ❌ Copied items keep the form the agent gave them
  (`inverser(phrase)` rather than `inverser`): the schema should specify the expected
  format (`description`) if it matters.
- Follow-up: if the web interface exposes `/structured`, give it the same step.
