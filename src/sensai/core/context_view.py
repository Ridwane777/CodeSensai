"""
`/context` : ce qui part réellement au modèle au prochain tour (ADR-0058).

La commande
affiche les paramètres envoyés à Ollama (num_ctx, paramètres de génération), le
budget de tokens, puis chaque message tel quel, avec son estimation de tokens.
La question du prochain tour n'y est pas encore : les passages RAG et l'exemple
few-shot y seront joints au moment de l'envoyer.
"""
from __future__ import annotations

from typing import Any

from sensai.knowledge.compression import count_message_tokens, count_tokens

COMMAND = "/context"


def describe_context(messages: list[dict[str, Any]], num_ctx: int | None,
                     budget: int | None, generation: dict[str, Any]) -> str:
    """Le texte de `/context` : les réglages, puis chaque message en entier."""
    total = count_message_tokens(messages)
    params = ", ".join(f"{k}={v}" for k, v in sorted(generation.items())) or "ceux du modèle"
    lines = [
        f"Contexte du prochain tour : {len(messages)} message(s), ~{total} tokens (estimés, "
        f"caractères / 4) ; num_ctx={num_ctx}, budget={budget}.",
        f"Paramètres de génération envoyés : {params}.",
        "Les passages RAG et l'exemple few-shot s'ajoutent à la question au moment de l'envoi.",
    ]
    for index, message in enumerate(messages, 1):
        content = str(message.get("content", ""))
        role = message.get("role", "?")
        lines.append(f"\n--- [{index}] {role} · ~{count_tokens(content)} tokens ---")
        lines.append(content)
    return "\n".join(lines)
