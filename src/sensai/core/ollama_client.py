"""
Client HTTP minimal pour l'API Ollama — AUCUN framework LLM (contrainte du sujet).
Tout passe par des appels HTTP directs via `requests`.
"""
import json
from collections.abc import Iterator
from typing import Any

import requests


class OllamaError(Exception):
    """Erreur levée quand Ollama est injoignable ou renvoie une erreur."""
    pass


# Paramètres de génération (ADR-0057) acceptés dans config.json, section
# `generation`, et envoyés dans `options` à chaque appel de chat. Les autres
# options d'Ollama restent possibles mais ne sont pas exposées.
GENERATION_KEYS = ("temperature", "top_p", "top_k", "seed", "num_predict", "repeat_penalty")

# Réglés une fois au démarrage (CLI, sensai-web, sensai-schedule) : tous les
# appels de chat passent par stream_chat_messages, un seul point suffit.
_generation: dict[str, Any] = {}


def set_generation_options(options: dict[str, Any] | None) -> None:
    """Paramètres de génération ajoutés à chaque appel (vide : ceux du modèle)."""
    _generation.clear()
    _generation.update({k: v for k, v in (options or {}).items() if v is not None})


def generation_options() -> dict[str, Any]:
    """Les paramètres en vigueur (affichés par /context)."""
    return dict(_generation)


def stream_chat_messages(
    host: str,
    model: str,
    messages: list[dict],
    tools: list[dict[str, Any]] | None = None,
    format: dict[str, Any] | str | None = None,
    options: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Envoie l'historique à Ollama et renvoie, au fil du streaming, le champ
    `message` de chaque morceau : `content`, `thinking` et `tool_calls`
    selon ce que le modèle produit.

    `tools` est passé tel quel dans le champ du même nom (ADR-0003) : Ollama
    renvoie alors les appels d'outils déjà structurés dans `tool_calls`, au
    lieu qu'on doive les deviner dans le texte.

    `format` est passé tel quel dans le champ du même nom (ADR-0036) : un
    schéma JSON pour contraindre la réponse à cette forme, ou `"json"`.

    `options` est passé tel quel dans le champ du même nom — notamment
    `num_ctx` (M2, ADR-0045) : sans lui, Ollama tronque l'historique à sa
    propre limite par défaut (2048 ou 4096 selon la version), en silence et
    bien avant le budget que M2 surveille.
    """
    url = f"{host}/api/chat"
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
    if format:
        payload["format"] = format
    # Les paramètres de génération réglés au démarrage, puis ceux de l'appel
    # (num_ctx…), qui l'emportent : le juge EV1 garde ainsi sa température 0.
    merged = {**_generation, **(options or {})}
    if merged:
        payload["options"] = merged

    try:
        response = requests.post(url, json=payload, stream=True, timeout=60)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise OllamaError(
            f"Impossible de contacter Ollama sur {host}. "
            "Vérifiez que `ollama serve` tourne bien."
        ) from e
    except requests.exceptions.Timeout as e:
        raise OllamaError("Ollama ne répond pas (timeout).") from e
    except requests.exceptions.HTTPError as e:
        detail = response.text[:200] if response is not None else str(e)
        raise OllamaError(f"Erreur Ollama : {detail}") from e

    for line in response.iter_lines():
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        if chunk.get("error"):
            raise OllamaError(chunk["error"])
        # Le dernier morceau (done=True) porte encore un `message`, en général
        # vide : on le transmet quand même plutôt que de parier qu'il l'est.
        message = chunk.get("message")
        if message:
            yield message
        if chunk.get("done"):
            break


def stream_chat(
    host: str, model: str, messages: list[dict], num_ctx: int | None = None
) -> Iterator[str]:
    """
    Envoie l'historique de conversation à Ollama et streame la réponse
    morceau par morceau (pas un seul bloc — exigence du sujet).

    `num_ctx` (M2, ADR-0045) : voir `stream_chat_messages`.
    """
    options = {"num_ctx": num_ctx} if num_ctx else None
    for message in stream_chat_messages(host, model, messages, options=options):
        content = message.get("content", "")
        if content:
            yield content
