"""
Sortie structurée garantie par schéma JSON — feature [T5] Structured Output.

Ollama contraint le décodage du modèle au schéma donné (champ `format` de
l'API `/api/chat`, ADR-0036) : la réponse est du JSON qui respecte la forme
demandée, pas un texte dont on espère extraire l'information.

Appel séparé de la boucle ReAct (core/agent.py) : `format` contraint et
`tools` ne se mélangent pas dans le même appel (voir ADR-0036).

En deux temps quand le CLI fournit `gather` (ADR-0039) : l'agent cherche
d'abord la réponse avec ses outils (lecture de fichiers, recherche dans le
projet…), puis l'appel contraint met en forme CE QU'IL A TROUVÉ. Sans cela,
le modèle répondait de mémoire et inventait (essai réel du 2026-10-24 : cinq
fonctions inventées pour un fichier qui n'en a qu'une).
"""
from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .ollama_client import OllamaError, stream_chat_messages

COMMAND = "/structured"
USAGE = f'Usage : {COMMAND} <schéma.json> <demande>'


class StructuredOutputError(Exception):
    """Le modèle n'a pas produit de JSON valide malgré la contrainte de schéma."""


def grounded_prompt(prompt: str, findings: str) -> str:
    """La demande, accompagnée de ce que l'agent a trouvé : seule source autorisée."""
    return (
        f"Demande : {prompt}\n\n"
        "Informations trouvées dans le projet par l'agent (seule source autorisée) :\n"
        f"{findings.strip() or '(rien trouvé)'}\n\n"
        "Remplis le schéma à partir de ces informations : recopie les éléments qu'elles "
        "donnent (noms, valeurs), sans en oublier et sans rien inventer. Ne laisse un "
        "champ vide que si l'information n'y figure vraiment pas."
    )


def run_structured_query(
    host: str, model: str, prompt: str, schema: dict[str, Any], num_ctx: int | None = None,
) -> dict[str, Any]:
    """Envoie `prompt` au modèle en exigeant une réponse conforme à `schema`.

    Un seul aller-retour, sans outils. Lève StructuredOutputError si la
    réponse n'est malgré tout pas du JSON valide (modèle indiscipliné, ou
    version d'Ollama trop ancienne pour comprendre `format`).

    `num_ctx` (M2, ADR-0045) : sans lui, Ollama tronque en silence un prompt
    long (le `/structured` appuyé sur le projet en colle des extraits).
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
            f"Réponse non conforme au schéma (JSON invalide) : {raw[:200]!r}"
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
    """`/structured <schéma.json> <demande>` ; None si `line` n'en est pas une.

    `query` remplace l'appel réel (tests) ; sans lui, c'est `run_structured_query`
    avec `num_ctx` (M2, ADR-0045).
    """
    if not is_structured_command(line):
        return None
    run = query or (lambda h, m, p, s: run_structured_query(h, m, p, s, num_ctx=num_ctx))
    try:
        words = shlex.split(line)[1:]
    except ValueError as e:
        return f"[Erreur] Commande illisible : {e}"
    if len(words) < 2:
        return USAGE

    schema_path, prompt = words[0], " ".join(words[1:])
    try:
        schema_text = Path(schema_path).read_text(encoding="utf-8")
    except OSError as e:
        return f"[Erreur] Schéma illisible ({schema_path}) : {e}"
    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as e:
        return f"[Erreur] Schéma invalide ({schema_path}) : {e}"

    try:
        if gather is not None:
            prompt = grounded_prompt(prompt, gather(prompt))
        result = run(host, model, prompt, schema)
    except StructuredOutputError as e:
        return f"[Erreur] {e}"

    return json.dumps(result, ensure_ascii=False, indent=2)
