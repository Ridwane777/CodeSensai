"""
Contrat commun à tous les outils que l'agent peut appeler (feature [T1] MCP).

Toute feature qui expose une capacité à l'agent — sandbox, RAG, outil MCP
externe — implémente ce protocole. C'EST ce contrat qui permet aux 3 lots de
travailler en parallèle sans se marcher dessus : l'agent ne connaît que le
ToolRegistry, jamais l'implémentation d'un outil.

Voir docs/decisions/0002-registre-d-outils-partage.md pour la justification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    # JSON schema décrivant les arguments attendus (utilisé pour le function
    # calling / la feature bonus [T5] Structured Output)
    parameters: dict[str, Any]
    # Attendu aussi par la passerelle d'outils (ADR-0006) : `risk`, parmi
    # "read", "network", "write", "execute". Absent = traité comme "execute",
    # donc confirmation demandée. Voir docs/architecture/tool-contract.md.

    def run(self, **kwargs) -> ToolResult:
        """Exécute l'outil. Ne doit JAMAIS lever d'exception non gérée : toute
        erreur doit être encodée dans ToolResult(ok=False, ...)."""
        ...


class ToolRegistry:
    """Registre central où chaque lot enregistre ses outils."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def describe_all(self) -> list[dict[str, Any]]:
        """Utilisé pour informer le modèle des outils disponibles."""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]

    # `name` est positionnel uniquement (le `/`) : sans ça, un outil dont un
    # paramètre s'appelle lui aussi `name` ferait planter l'appel AVANT le try
    # ci-dessous (« got multiple values for argument 'name' »).
    def call(self, name: str, /, **kwargs) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(ok=False, content=f"Outil inconnu : {name}")
        try:
            return tool.run(**kwargs)
        except Exception as e:  # garde-fou : un outil qui plante ne doit pas planter l'agent
            return ToolResult(ok=False, content=f"Erreur dans l'outil {name} : {e}")
