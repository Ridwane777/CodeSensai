# ADR-0036 — Structured output via Ollama's `format` field (JSON schema)

- **Status**: Accepted
- **Date**: 2026-10-23
- **Deciders**: Fresnel (Workstream A)
- **Workstream**: A (`core/`)

## Context

[T5] Structured Output requires getting a response from the model that
follows a precise shape (a JSON object with given fields and
types), so a program can consume it without guessing where the
information is in free text.

The project spec forbids any LLM framework: the solution must go through Ollama's
HTTP API, like the rest of the project (see `core/ollama_client.py`).

## Considered options

| Option | Pros | Cons |
| --- | --- | --- |
| Ask for JSON in the prompt ("answer in JSON with the fields...") | No code, no dependency | No guarantee: the model adds text around it, forgets a field, or writes invalid JSON. Measured on `qwen3-coder`: fails one time in three on a 4-field request. |
| Ollama's native `format` field on the `/api/chat` API (JSON Schema or `"json"`) | The model's decoding is constrained token by token: the output is guaranteed to follow the schema's shape (field names, types). Already the mechanism used for native tool calling (ADR-0003) — same API family. | Requires a recent Ollama version; only guarantees the *shape*, not that the *values* make sense; does not mix with tools in the same call (see Decision). |
| Validate afterwards with the `jsonschema` library | Finer validation (formats, numeric bounds) | New dependency for a problem `format` already solves at the source; an extra ADR to write to justify it (repo rule on major dependencies). |

## Decision

We use the `format` field of Ollama's `/api/chat` API, passing it the
requested JSON schema. `stream_chat_messages` (existing ADR on
`ollama_client.py`) gains an optional `format` parameter passed as is
in the payload, exactly like `tools`.

Structured output is a **separate** call from the ReAct loop
(`core/structured.py`, `run_structured_query`): a single round trip, with no
tools. Mixing tool calling and constrained `format` in the same call is
not a documented, stable behavior of the Ollama API; separating the two
avoids guessing which one wins.

Exposed in the chat via `/structured <schema-file.json> <prompt>`, modeled on
the `/schedule` and `/eval` commands (ADR-0028): a command that
calls the core (Workstream A) without going through the agent loop.

## Consequences

- ✅ Structural guarantee (field names, types, nesting) provided by
  Ollama itself, with no extra dependency.
- ✅ Same mechanism as native tool calling (ADR-0003): nothing new to
  learn on the HTTP client side, just one more payload field.
- ❌ No semantic validation (an integer in the right range, a correct
  date format, an enum value respected): `format`
  guarantees the shape, not the meaning. If that becomes necessary, it will be a
  new ADR for `jsonschema`, not a rewrite of this one.
- ❌ Assumes an Ollama version that understands `format` as JSON Schema (not
  just `"json"`); on a version that is too old, the call fails or
  Ollama silently ignores the constraint — `run_structured_query` raises
  `StructuredOutputError` if the response is still not valid JSON,
  but cannot distinguish that case from an undisciplined model.
- Follow-up: if a schema with fine constraints (regex, min/max, enum) is
  actually needed for a catalog feature, re-evaluate `jsonschema`
  at that point rather than in advance.
