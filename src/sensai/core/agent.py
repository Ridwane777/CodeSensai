"""
Boucle de raisonnement de l'agent — feature [A1] Reasoning Loops (ReAct).

Le cycle Thought -> Action -> Observation s'appuie sur le tool calling natif
d'Ollama (ADR-0003) : la liste des outils part dans le champ `tools` de la
requête, et la décision d'agir se lit dans `message.tool_calls`, déjà
structuré par Ollama. Le texte écrit par le modèle n'est JAMAIS interprété
comme une commande : il est affiché, pas exécuté.

Un tour émet des ÉVÉNEMENTS (core/events.py), pas du texte : voir ADR-0005
et docs/architecture/web/api-contract.md.

L'agent n'exécute jamais un outil lui-même : il passe par la passerelle
d'outils du Lot B (execution/gateway.py, ADR-0006), qui applique permissions,
validation, garde-fous et confirmation avant action risquée. Ce module ne
l'importe pas — c'est l'interface qui la construit et la lui donne — pour
que le cœur ne dépende pas du Lot B.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any, Protocol

from ..execution.guardrails import StreamRedactor, filter_output
from ..execution.output_sanitizer import fence_untrusted
from .events import Done, Error, Event, Thought, Token, ToolCall, ToolReturn
from .ollama_client import OllamaError, stream_chat_messages
from .tools import ToolRegistry, ToolResult

# Appel d'outil écrit dans le texte au lieu du champ `tool_calls` : qwen3-coder
# oublie parfois la balise <tool_call> d'ouverture, et Ollama ne reconnaît
# alors pas l'appel. Mesuré le 2026-10-17 : environ 3 réponses sur 10 sur une
# demande comme « retiens que… », avec ou sans notre prompt. Si la réponse
# n'est que des appels, on les lit (ADR-0031) ; sinon rien n'est exécuté et on
# redemande la même chose sans garder la réponse ratée : la lui renvoyer
# l'incite à la recopier (constaté pendant l'essai).
TEXTUAL_TOOL_CALL = re.compile(r"<function=[A-Za-z_][\w.-]*>|<tool_call>")
MAX_TEXTUAL_CALL_RETRIES = 2
_STRAY_TAGS = re.compile(r"</?tool_call>")
# ADR-0031 : quand la réponse n'est QUE des appels au format natif de
# qwen3-coder, on les lit et ils suivent le chemin normal (passerelle,
# garde-fous, confirmation). Un appel mêlé à du texte n'est jamais lu.
_CALL = re.compile(
    r"\s*(?:<tool_call>\s*)?<function=([A-Za-z_][\w.-]*)>(.*?)</function>\s*(?:</tool_call>)?\s*",
    re.S,
)
_PARAM = re.compile(r"\s*<parameter=([A-Za-z_][\w.-]*)>\n?(.*?)\n?</parameter>\s*", re.S)
MAX_ITERATIONS = 6  # garde-fou anti-boucle infinie : nombre maximal d'appels au modèle par tour



class ToolCaller(Protocol):
    """Ce dont l'agent a besoin pour utiliser des outils : en pratique la
    ToolGateway (execution/gateway.py), jamais le ToolRegistry brut."""

    def describe_all(self) -> list[dict[str, Any]]: ...

    def call(self, name: str, /, **kwargs: Any) -> ToolResult: ...


def ollama_tools(tools: ToolCaller) -> list[dict[str, Any]]:
    """Met les descriptions des outils au format du champ `tools` d'Ollama.

    L'enveloppe {"type": "function", ...} est un détail de l'API Ollama :
    elle reste ici, pour que le contrat Tool (ADR-0002) n'en dépende pas.
    """
    return [{"type": "function", "function": d} for d in tools.describe_all()]


def run_agent_turn(
    host: str,
    model: str,
    messages: list[dict],
    tools: ToolCaller,
    num_ctx: int | None = None,
    max_iterations: int | None = None,
) -> Iterator[Event]:
    """
    Joue un tour d'agent et émet ce qui s'y passe, au fil de l'eau.

    À chaque itération : on appelle le modèle ; s'il demande des outils, on
    les exécute, on lui renvoie les résultats et on recommence ; sinon sa
    réponse est la réponse finale. Au-delà de `max_iterations` appels au modèle
    (MAX_ITERATIONS par défaut), le tour s'arrête avec Done(reason="max_iterations").

    `messages` n'est pas modifié : les échanges internes du tour (appels
    d'outils, résultats) restent dans une copie. C'est l'appelant qui décide
    de ce qu'il garde dans son historique.

    `tools` est la passerelle d'outils. La confirmation avant action risquée
    est branchée dessus par l'interface, pas passée ici.

    `num_ctx` (M2, ADR-0045) : sans lui, Ollama tronque l'historique en
    silence à sa propre limite par défaut, avant même que le budget suivi
    par cli.py ait eu l'occasion de résumer quoi que ce soit. `None` laisse
    Ollama décider (compatibilité : la plupart des appelants ne le passent
    pas).
    """
    options = {"num_ctx": num_ctx} if num_ctx else None
    # Nombre maximal d'appels au modèle par tour : réglable (`max_iterations` dans
    # config.json, --max-iterations), MAX_ITERATIONS par défaut.
    limit = max_iterations or MAX_ITERATIONS
    # Le registre brut a les mêmes méthodes que la passerelle : sans ce
    # refus explicite, le brancher par erreur exécuterait les outils sans
    # permissions, garde-fous ni confirmation, et sans que rien ne casse.
    if isinstance(tools, ToolRegistry):
        raise TypeError(
            "run_agent_turn attend la ToolGateway (ADR-0006), pas le ToolRegistry brut."
        )
    messages = list(messages)
    offered = ollama_tools(tools)
    schemas = {t["function"]["name"]: t["function"].get("parameters") or {} for t in offered}
    textual_retries = 0

    for iteration in range(limit):
        content: list[str] = []
        thinking: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        # EV2 : la réponse affichée et enregistrée passe par filter_output, ligne
        # par ligne ; le modèle, lui, garde son propre texte dans `messages`.
        redactor = StreamRedactor()

        try:
            for message in stream_chat_messages(host, model, messages, offered,
                                                 options=options):
                if message.get("thinking"):
                    thinking.append(message["thinking"])
                if message.get("content"):
                    # Le raisonnement précède la réponse : on le livre d'un
                    # bloc dès que la réponse commence, plutôt que mot à mot
                    # — un Thought par mot serait illisible dans les deux
                    # interfaces.
                    yield from _flush_thought(thinking)
                    content.append(message["content"])
                    # Émis même vide : chaque morceau reste un point où le tour peut
                    # être interrompu (Échap, « Arrêter »), sans attendre la fin de ligne.
                    yield Token(text=redactor.feed(message["content"]))
                tool_calls.extend(message.get("tool_calls") or [])
        except OllamaError as e:
            yield Error(message=str(e))
            yield Done(reason="error")
            return

        yield from _flush_thought(thinking)
        rest = redactor.flush()
        if rest:
            yield Token(text=rest)

        if not tool_calls:
            reply = "".join(content)
            if not TEXTUAL_TOOL_CALL.search(reply):
                yield Done()
                return
            if "<function=" not in reply and _STRAY_TAGS.sub("", reply).strip():
                # Une balise <tool_call> vide après une vraie réponse : rien à exécuter.
                # Essai réel du 2026-11-01 : relancé trois fois, le tour finissait en
                # échec alors que la réponse (et l'outil appelé avant) étaient bons.
                yield Done()
                return
            tool_calls = _read_textual_calls(reply, schemas)
            if tool_calls:
                yield Thought(text="Appel d'outil lu dans le texte (non reconnu par Ollama).")
                content = []
        if not tool_calls:
            if textual_retries >= MAX_TEXTUAL_CALL_RETRIES or iteration == limit - 1:
                # Toujours illisible après les relances : on arrête plutôt que de laisser le modèle
                # affirmer une action qui n'a pas eu lieu.
                yield Error(message=(
                    "Le modèle a écrit un appel d'outil dans le texte au lieu de "
                    "l'appeler : il n'a pas été exécuté. Reformule la demande."
                ))
                yield Done(reason="error")
                return
            textual_retries += 1
            yield Thought(text="Appel d'outil écrit en texte, non exécuté : nouvel essai.")
            continue

        # Ollama a besoin de revoir sa propre demande d'outils avant les
        # résultats : sans ce message, les réponses `role: "tool"` qui
        # suivent ne se rattachent à rien.
        messages.append(
            {"role": "assistant", "content": "".join(content), "tool_calls": tool_calls}
        )

        for index, call in enumerate(tool_calls):
            function = call.get("function") or {}
            name = function.get("name", "")
            # Ollama fournit un id ; s'il manque, on en fabrique un unique
            # dans le tour — l'interface en a besoin pour relier l'appel à
            # son résultat.
            call_id = call.get("id") or f"{iteration}-{index}"
            arguments, problem = _parse_arguments(function.get("arguments"))

            yield ToolCall(id=call_id, name=name, arguments=arguments)
            if problem:
                # Revient au modèle comme une observation, pour qu'il corrige
                # son appel : ce n'est pas une erreur du tour.
                result = ToolResult(ok=False, content=problem)
            else:
                result = tools.call(name, **arguments)
            yield ToolReturn(id=call_id, name=name, ok=result.ok, content=result.content)

            # Le modèle reçoit le résultat enfermé dans <tool_output trust="untrusted">
            # (EV4-OUT-14) : une page web ou un fichier lu peut contenir des
            # instructions, et le prompt système (date_block) dit de ne pas les suivre.
            # L'interface, elle, affiche le résultat tel quel (ToolReturn ci-dessus).
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "tool_call_id": call_id,
                    "content": fence_untrusted(name, result.content),
                }
            )

    yield Done(reason="max_iterations")


def _read_textual_calls(reply: str, schemas: dict[str, dict]) -> list[dict[str, Any]]:
    """Appels écrits au format natif de qwen3-coder, si la réponse n'est QUE ça.

    Renvoie [] si la réponse contient autre chose, si un appel est mal formé
    ou vise un outil non proposé : rien n'est alors exécuté (ADR-0031).
    """
    calls, position = [], 0
    for match in _CALL.finditer(reply):
        if match.start() != position:
            return []
        position = match.end()
        name, body = match.group(1), match.group(2)
        if name not in schemas:
            return []
        arguments, inner = {}, 0
        for param in _PARAM.finditer(body):
            if param.start() != inner:
                return []
            inner = param.end()
            arguments[param.group(1)] = _typed(param.group(2), schemas[name], param.group(1))
        if body[inner:].strip():
            return []
        calls.append({"function": {"name": name, "arguments": arguments}})
    return calls if calls and position == len(reply) else []


def _typed(raw: str, schema: dict, key: str) -> Any:
    """Convertit une valeur lue dans le texte selon le type attendu par l'outil ;
    en cas de doute, la laisse en texte (la passerelle validera)."""
    kind = ((schema.get("properties") or {}).get(key) or {}).get("type")
    try:
        if kind == "integer":
            return int(raw.strip())
        if kind == "number":
            return float(raw.strip())
        if kind == "boolean" and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
    except ValueError:
        pass
    return raw


def _flush_thought(thinking: list[str]) -> Iterator[Thought]:
    """Émet le raisonnement accumulé en un seul Thought, puis vide le tampon.

    Filtré comme la réponse (EV2, ADR-0058) : il est affiché et enregistré lui aussi.
    Livré d'un bloc, il peut l'être en entier, sans attendre des fins de ligne."""
    text = filter_output("".join(thinking).strip())
    thinking.clear()
    if text:
        yield Thought(text=text)


def _parse_arguments(raw: Any) -> tuple[dict[str, Any], str | None]:
    """Valide les arguments d'un appel d'outil.

    Ollama les renvoie normalement déjà désérialisés, mais c'est le modèle
    qui les écrit : on ne leur fait pas confiance. Retourne
    (arguments, problème) — un problème non nul empêche l'exécution.
    """
    if raw is None:
        return {}, None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}, "Arguments illisibles : ce n'est pas du JSON valide."
    if not isinstance(raw, dict):
        return {}, "Arguments invalides : un objet JSON était attendu."
    return raw, None
