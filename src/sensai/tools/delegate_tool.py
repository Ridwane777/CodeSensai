"""
Délégation d'une sous-tâche à un sous-agent — feature [A2] Multi-Agent
Orchestration (ADR-0037).

L'agent principal décompose une tâche complexe en sous-tâches et délègue
chacune à un sous-agent qui joue sa propre boucle ReAct (core/agent.py), avec
son propre historique (isolé de la conversation en cours) et, optionnellement,
son propre rôle (persona). Le sous-agent appelle les MÊMES outils, à travers
la MÊME passerelle (ADR-0006) : une action risquée demande confirmation que
ce soit l'agent principal ou un sous-agent qui la décide, et les garde-fous
EV2 s'appliquent pareil.

Choix mesurés avec le vrai modèle :
- le sous-agent reçoit le prompt du projet (profil, SENSAI.md, faits), sinon il
  ignore ce que l'agent principal sait et peut le contredire ;
- un sous-agent ne redélègue pas (MAX_DELEGATION_DEPTH = 1) : en profondeur 2,
  un sous-agent perdu a redélégué trois fois et rendu une réponse vide en 120 s ;
- il s'arrête à son échéance : sans cela, il continuait après l'abandon et
  demandait encore des confirmations d'écriture que personne n'attendait.
"""
from __future__ import annotations

import contextvars
import functools
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from sensai.core.agent import ToolCaller
from sensai.core.agent import run_agent_turn as _run_agent_turn
from sensai.core.events import Done, Error, Token
from sensai.core.tools import ToolResult

MAX_DELEGATION_DEPTH = 1
# La passerelle garde le plus court des deux délais (le sien, 120 s par défaut,
# et celui-ci). Le sous-agent s'arrête bien avant : l'échéance n'est vérifiée
# qu'entre deux événements, et un appel au modèle déjà lancé peut durer une
# vingtaine de secondes (mesuré : 5 s de marge ne suffisaient pas).
DELEGATION_TIMEOUT_S = 120.0
STOP_MARGIN_S = 30.0

_depth: contextvars.ContextVar[int] = contextvars.ContextVar("delegation_depth", default=0)

# Les outils qui lancent d'autres agents : jamais proposés à un sous-agent.
DELEGATION_TOOLS = frozenset({"delegate_task", "team_task"})


# Jamais proposés à un sous-agent, quel que soit son rôle : planifier une tâche qui
# rejouera un prompt sans surveillance reste une décision de l'agent principal, sur
# accord de l'utilisateur (ADR-0052).
NEVER_DELEGATED = frozenset({"schedule_task"})


@dataclass(frozen=True)
class Role:
    """Un agent spécialisé (A2, ADR-0038) : ses consignes et les seuls outils qu'il voit."""

    prompt: str
    tools: frozenset[str]


# list_files (ADR-0059) : sans RAG, seul moyen pour un rôle de voir les fichiers du projet.
_READ = frozenset({"read_file", "list_files", "search_codebase", "recall_facts"})
ROLES: dict[str, Role] = {
    "explorateur": Role(
        "Tu es l'explorateur de l'équipe. Tu lis et cherches dans le projet, tu ne "
        "modifies rien. Rends un rapport court et factuel : les fichiers et fonctions "
        "concernés, ce qu'ils font, les contraintes à respecter pour la tâche.",
        _READ | {"web_search"},
    ),
    "developpeur": Role(
        "Tu es le développeur de l'équipe. À partir de la tâche et du travail reçu, "
        "produis la modification demandée. Si la tâche demande d'écrire un fichier, "
        "utilise write_file. Termine par le code produit et un résumé de ce que tu as fait.",
        _READ | {"write_file", "run_code"},
    ),
    "relecteur": Role(
        "Tu es le relecteur de l'équipe, et tu ne modifies rien. Ne crois pas le compte "
        "rendu du développeur : avant de juger, lis toujours avec read_file chaque fichier "
        "concerné, puis vérifie le code ligne par ligne au regard de la tâche, en essayant "
        "mentalement quelques exemples (dont des cas limites). Commence ta réponse par "
        "VALIDÉ seulement si le code lu est correct ; sinon commence par À CORRIGER, suivi "
        "de la liste précise des défauts.",
        _READ,
    ),
}


class AgentRunner(Protocol):
    """Ce dont DelegateTool a besoin pour jouer le tour d'un sous-agent : en
    pratique run_agent_turn (core/agent.py), remplacé en test par un faux tour."""

    def __call__(self, host: str, model: str, messages: list[dict], tools: ToolCaller) -> Any: ...


class _SubAgentTools:
    """La passerelle vue par un sous-agent : ni les outils de délégation (il ne
    redélègue pas) ni ceux hors de son rôle ne lui sont proposés, et après
    l'échéance plus aucun outil ne s'exécute ni ne demande de confirmation."""

    def __init__(
        self,
        tools: ToolCaller,
        deadline: float,
        role: Role | None,
        on_call: Callable[[str, dict, ToolResult], None] | None = None,
    ) -> None:
        self.tools, self.deadline, self.role, self.on_call = tools, deadline, role, on_call

    def _allowed(self, name: str) -> bool:
        if name in NEVER_DELEGATED:
            return False
        if name in DELEGATION_TOOLS:
            return False
        return self.role is None or name in self.role.tools

    def describe_all(self) -> list[dict[str, Any]]:
        return [d for d in self.tools.describe_all() if self._allowed(d.get("name", ""))]

    def call(self, name: str, /, **kwargs: Any) -> ToolResult:
        if name in DELEGATION_TOOLS:
            return ToolResult(
                ok=False, content="Un sous-agent ne redélègue pas : fais cette sous-tâche toi-même."
            )
        if not self._allowed(name):
            return ToolResult(ok=False, content=f"Outil « {name} » non autorisé pour ce rôle.")
        if time.monotonic() >= self.deadline:
            return ToolResult(
                ok=False, content="Délai de la sous-tâche dépassé : outil non exécuté."
            )
        result = self.tools.call(name, **kwargs)
        if self.on_call:
            self.on_call(name, kwargs, result)
        return result


class DelegateTool:
    name = "delegate_task"
    description = (
        "Délègue une sous-tâche à un sous-agent, qui la traite avec les mêmes outils et "
        "renvoie sa réponse. Utilise-le quand la demande porte sur plusieurs fichiers ou "
        "parties indépendants (trois ou plus) : délègue une sous-tâche par fichier ou par "
        "partie, puis assemble les réponses. Ne l'utilise pas pour une question simple ni "
        "pour un ou deux fichiers : fais-le toi-même. Le sous-agent ne voit pas la "
        "conversation : chaque sous-tâche doit se comprendre seule."
    )
    # Le sous-agent peut appeler n'importe quel outil, y compris risqué : ce
    # qui compte est le risque de CHAQUE appel qu'il fera, filtré par la même
    # passerelle. Déclarer "execute" ici évite qu'une politique permissive sur
    # ce seul outil serve à contourner les confirmations des outils utilisés.
    risk = "execute"
    timeout_s = DELEGATION_TIMEOUT_S
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "La sous-tâche à accomplir, formulée comme une consigne autonome "
                    "(le sous-agent ne voit pas la conversation en cours)."
                ),
            },
            "role": {
                "type": "string",
                "enum": sorted(ROLES),
                "description": (
                    "Agent spécialisé : explorateur (lit et cherche, ne modifie rien), "
                    "developpeur (peut écrire), relecteur (vérifie, ne modifie rien). Optionnel."
                ),
            },
            "persona": {
                "type": "string",
                "description": (
                    "Rôle à donner au sous-agent (ex. « relectrice de sécurité »). Optionnel."
                ),
            },
        },
        "required": ["task"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        host: str,
        model: str,
        tools: ToolCaller,
        run_turn: AgentRunner | None = None,
        system_prompt: Callable[[], str] | None = None,
        num_ctx: int | None = None,
    ) -> None:
        self.host = host
        self.model = model
        self.tools = tools
        # M2, ADR-0045 : sans num_ctx, un sous-agent reste soumis à la troncature
        # par défaut d'Ollama, que le CLI a pourtant évitée pour la boucle
        # principale. `run_turn` explicite (tests) est utilisé tel quel.
        self.run_turn = run_turn or functools.partial(_run_agent_turn, num_ctx=num_ctx)
        # Le prompt du projet (profil, SENSAI.md, faits), relu à chaque
        # délégation comme le CLI le relit à chaque tour.
        self.system_prompt = system_prompt

    def describe_call(self, **args: Any) -> str:
        """Ce que l'utilisateur est invité à approuver : la sous-tâche en clair."""
        who = args.get("role") or args.get("persona")
        task = args.get("task", "")
        return f"Déléguer à un sous-agent ({who}) : {task}" if who else f"Déléguer : {task}"

    def _system(self, role: Role | None, persona: str | None) -> str:
        parts = [self.system_prompt() if self.system_prompt else ""]
        if role:
            parts.append(role.prompt)
        if persona:
            parts.append(f"Ton rôle pour cette sous-tâche : {persona}" if any(parts) else persona)
        return "\n\n".join(p for p in parts if p)

    def run(self, **kwargs) -> ToolResult:
        return self.delegate(
            kwargs.get("task") or "", role=kwargs.get("role"), persona=kwargs.get("persona")
        )

    def delegate(
        self,
        task: str,
        *,
        role: str | None = None,
        persona: str | None = None,
        deadline: float | None = None,
        on_call: Callable[[str, dict, ToolResult], None] | None = None,
    ) -> ToolResult:
        """Fait tourner un sous-agent jusqu'à sa réponse ou son échéance
        (`deadline`, en time.monotonic() ; par défaut celle de cet outil).
        `on_call` voit chaque outil exécuté par le sous-agent (l'équipe s'en sert
        pour savoir ce que le développeur a vraiment écrit)."""
        if not task.strip():
            return ToolResult(ok=False, content="La sous-tâche est vide.")
        if role and role not in ROLES:
            return ToolResult(
                ok=False, content=f"Rôle inconnu : {role} (rôles : {', '.join(sorted(ROLES))})."
            )
        spec = ROLES[role] if role else None

        depth = _depth.get()
        if depth >= MAX_DELEGATION_DEPTH:
            return ToolResult(
                ok=False,
                content=(
                    f"Profondeur de délégation dépassée ({MAX_DELEGATION_DEPTH}) : un "
                    "sous-agent ne redélègue pas, accomplis cette sous-tâche toi-même."
                ),
            )

        messages: list[dict] = []
        system = self._system(spec, persona)
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": task})

        if deadline is None:
            deadline = time.monotonic() + self.timeout_s - STOP_MARGIN_S
        token = _depth.set(depth + 1)
        content: list[str] = []
        errors: list[str] = []
        max_iterations = timed_out = False
        tools = _SubAgentTools(self.tools, deadline, spec, on_call)
        turn = self.run_turn(self.host, self.model, messages, tools)
        try:
            for event in turn:
                if isinstance(event, Token):
                    content.append(event.text)
                elif isinstance(event, Error):
                    errors.append(event.message)
                elif isinstance(event, Done) and event.reason == "max_iterations":
                    max_iterations = True
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
        finally:
            close = getattr(turn, "close", None)
            if close:
                close()  # arrête vraiment le sous-agent : rien ne continue en arrière-plan
            _depth.reset(token)

        reply = "".join(content).strip()
        if errors:
            return ToolResult(ok=False, content=f"Le sous-agent a échoué : {' ; '.join(errors)}")
        if timed_out:
            partial = f" Réponse partielle :\n{reply}" if reply else ""
            return ToolResult(
                ok=False,
                content=(
                    "Le sous-agent a atteint son délai et s'est arrêté." + partial
                ),
            )
        if not reply:
            return ToolResult(ok=False, content="Le sous-agent n'a produit aucune réponse.")
        if max_iterations:
            reply += "\n[sous-agent arrêté après le nombre maximal d'itérations]"
        return ToolResult(ok=True, content=reply)
