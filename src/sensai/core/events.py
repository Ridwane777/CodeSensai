"""
Ce que l'agent émet pendant un tour — le contrat entre le cœur et les
interfaces (ADR-0005).

L'idée : un tour d'agent ne produit pas « du texte », il produit une suite
d'ÉVÉNEMENTS. Le modèle réfléchit, appelle un outil, reçoit un résultat,
puis répond. Chacune de ces étapes est un événement distinct.

Pourquoi ça plutôt qu'un flux de texte : la CLI affiche ces événements dans
un terminal, l'interface web les envoie au navigateur en JSON. Les deux
consomment la MÊME source. Si le cœur renvoyait du texte déjà mis en forme,
le web devrait le redécouper — c'est-à-dire reconstruire une logique qui
appartient au cœur, exactement ce qu'ADR-0005 interdit.

Conséquence pratique : ajouter un type d'événement ici oblige à décider ce
que chaque interface en fait. C'est voulu — c'est ce qui empêche les deux
interfaces de diverger sans que personne le remarque.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Token:
    """Un morceau de la réponse finale, à afficher au fil de l'eau."""
    text: str


@dataclass
class Thought:
    """Le raisonnement de l'agent avant d'agir — l'exigence de transparence.

    Séparé de Token pour que les interfaces puissent le présenter autrement :
    grisé dans le terminal, repliable dans le navigateur. Jamais confondu
    avec la réponse à l'utilisateur.
    """
    text: str


@dataclass
class ToolCall:
    """L'agent demande l'exécution d'un outil."""
    id: str  # relie l'appel à son ToolReturn : deux outils peuvent tourner à la suite
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolReturn:
    """Le résultat d'un ToolCall, tel que le registre l'a renvoyé."""
    id: str
    name: str
    ok: bool
    content: str


@dataclass
class Error:
    """Un échec qui interrompt le tour (Ollama injoignable, etc.).

    Un outil qui échoue n'est PAS une Error : c'est un ToolReturn(ok=False),
    et l'agent continue. Error veut dire « ce tour est perdu ».
    """
    message: str


@dataclass
class Done:
    """Fin du tour. Toujours le dernier événement, y compris après une Error.

    Les interfaces s'en servent pour savoir quand rendre la main : réafficher
    le prompt en CLI, fermer le flux côté web.
    """
    reason: str = "final_answer"  # ou "error", ou "max_iterations"


Event = Token | Thought | ToolCall | ToolReturn | Error | Done

# Nom transmis sur le réseau pour chaque type. Explicite plutôt que déduit du
# nom de la classe : renommer une classe ne doit pas casser l'interface web.
_WIRE_NAMES = {
    Token: "token",
    Thought: "thought",
    ToolCall: "tool_call",
    ToolReturn: "tool_return",
    Error: "error",
    Done: "done",
}


def to_wire(event: Event) -> dict[str, Any]:
    """Sérialise un événement pour l'interface web (JSON).

    La CLI n'en a pas besoin : elle lit les objets directement.
    """
    name = _WIRE_NAMES.get(type(event))
    if name is None:
        raise TypeError(f"Type d'événement inconnu : {type(event).__name__}")
    return {"type": name, **vars(event)}
