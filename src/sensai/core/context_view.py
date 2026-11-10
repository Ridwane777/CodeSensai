"""
`/context`: what actually goes to the model on the next turn (ADR-0058).

The command shows the parameters sent to Ollama (num_ctx, generation
parameters), the token budget, then each message as is, with its token
estimate. The next turn's question is not there yet: RAG passages and the
few-shot example are attached to it when it is sent.
"""
from __future__ import annotations

from typing import Any

from sensai.knowledge.compression import count_message_tokens, count_tokens

COMMAND = "/context"


def describe_context(messages: list[dict[str, Any]], num_ctx: int | None,
                     budget: int | None, generation: dict[str, Any]) -> str:
    """The text of `/context`: the settings, then each message in full."""
    total = count_message_tokens(messages)
    params = ", ".join(f"{k}={v}" for k, v in sorted(generation.items())) or "the model's defaults"
    lines = [
        f"Next turn context: {len(messages)} message(s), ~{total} tokens (estimated, "
        f"characters / 4); num_ctx={num_ctx}, budget={budget}.",
        f"Generation parameters sent: {params}.",
        "RAG passages and the few-shot example are added to the question when it is sent.",
    ]
    for index, message in enumerate(messages, 1):
        content = str(message.get("content", ""))
        role = message.get("role", "?")
        lines.append(f"\n--- [{index}] {role} · ~{count_tokens(content)} tokens ---")
        lines.append(content)
    return "\n".join(lines)
