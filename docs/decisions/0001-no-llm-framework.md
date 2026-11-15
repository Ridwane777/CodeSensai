# ADR-0001 - No LLM framework, raw HTTP calls to Ollama

Date: 2026-09-21
Workstream: All
Status: accepted - project constraint

## Context
The CodeSensai requirements explicitly forbid LLM frameworks (LangChain,
LlamaIndex, Haystack or equivalent) and require every model call to go
through the Ollama HTTP API directly.

## Considered options
- Use a framework anyway and justify it in the presentation - rejected,
  directly violates a mandatory project constraint.
- Build a small in-house abstraction layer on top of `requests` - chosen.

## Decision
All model calls go through `core/ollama_client.py`, which wraps `requests`
as raw HTTP. No dependency on an LLM orchestration framework is added to
`requirements.txt`.

## Consequences
- We write streaming, history management and function calling (via
  `core/tools.py`) ourselves - more work, but understanding these mechanisms
  is an explicit goal of the project.
- The Ollama client stays small and fully readable by all 3 team members
  (bootstrap depth test).
