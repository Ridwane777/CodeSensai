"""
Output guaranteed by a JSON schema - feature [T5] Structured Output.

Ollama constrains the model's decoding to the given schema (`format` field of
the `/api/chat` API, ADR-0036): the reply is JSON matching the requested
shape, not text we hope to extract information from.

A call separate from the ReAct loop (core/agent.py): constrained `format` and
`tools` do not mix in the same call (see ADR-0036).

Two steps when the CLI provides `gather` (ADR-0039): the agent first looks for
the answer with its tools (reading files, searching the project…), then the
constrained call formats WHAT IT FOUND. Without this, the model answered from
memory and made things up (real trial run on 2026-10-24: five invented
functions for a file that has only one).
"""
from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .ollama_client import OllamaError, stream_chat_messages

COMMAND = "/structured"
USAGE = f'Usage: {COMMAND} <schema.json> <request>'


class StructuredOutputError(Exception):
    """The model did not produce valid JSON despite the schema constraint."""


def grounded_prompt(prompt: str, findings: str) -> str:
    """The request, together with what the agent found: the only allowed source."""
    return (
        f"Request: {prompt}\n\n"
        "Information found in the project by the agent (the only allowed source):\n"
        f"{findings.strip() or '(nothing found)'}\n\n"
        "Fill in the schema from this information: copy the items it gives "
        "(names, values), without leaving any out and without inventing anything. Leave a "
        "field empty only if the information is really not there."
    )


def run_structured_query(
    host: str, model: str, prompt: str, schema: dict[str, Any], num_ctx: int | None = None,
) -> dict[str, Any]:
    """Send `prompt` to the model, requiring a reply that matches `schema`.

    A single round trip, no tools. Raises StructuredOutputError if the reply
    is still not valid JSON (undisciplined model, or an Ollama version too old
    to understand `format`).

    `num_ctx` (M2, ADR-0045): without it, Ollama silently truncates a long
    prompt (the project-grounded `/structured` pastes excerpts into it).
    """
    messages = [{"role": "user", "content": prompt}]
    chunks: list[str] = []
    extra = {"options": {"num_ctx": num_ctx}} if num_ctx else {}
    try:
        for message in stream_chat_messages(host, model, messages, format=schema, **extra):
            if message.get("content"):
                chunks.append(message["content"])
    except OllamaError as e:
        raise StructuredOutputError(str(e)) from e

    raw = "".join(chunks).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise StructuredOutputError(
            f"Reply does not match the schema (invalid JSON): {raw[:200]!r}"
        ) from e


def is_structured_command(line: str) -> bool:
    parts = line.split(None, 1)
    return bool(parts) and parts[0] == COMMAND


def handle_structured_command(
    line: str,
    *,
    host: str,
    model: str,
    query: Callable[[str, str, str, dict], dict] | None = None,
    gather: Callable[[str], str] | None = None,
    num_ctx: int | None = None,
) -> str | None:
    """`/structured <schema.json> <request>`; None if `line` is not one.

    `query` replaces the real call (tests); without it, `run_structured_query`
    is used with `num_ctx` (M2, ADR-0045).
    """
    if not is_structured_command(line):
        return None
    run = query or (lambda h, m, p, s: run_structured_query(h, m, p, s, num_ctx=num_ctx))
    try:
        words = shlex.split(line)[1:]
    except ValueError as e:
        return f"[Error] Unreadable command: {e}"
    if len(words) < 2:
        return USAGE

    schema_path, prompt = words[0], " ".join(words[1:])
    try:
        schema_text = Path(schema_path).read_text(encoding="utf-8")
    except OSError as e:
        return f"[Error] Unreadable schema ({schema_path}): {e}"
    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as e:
        return f"[Error] Invalid schema ({schema_path}): {e}"

    try:
        if gather is not None:
            prompt = grounded_prompt(prompt, gather(prompt))
        result = run(host, model, prompt, schema)
    except StructuredOutputError as e:
        return f"[Error] {e}"

    return json.dumps(result, ensure_ascii=False, indent=2)
