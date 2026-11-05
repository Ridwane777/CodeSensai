"""
[Lot C — Ridwane] Expose la mise à jour du document d'état (SENSAI.md) comme
un Tool appelable par l'agent — feature [M4], ADR-0029.

Risque `write` : chaque mise à jour passe par la confirmation de la passerelle
(A3), qui affiche `describe_call`, c'est-à-dire la section avant et après.
"""
from __future__ import annotations

from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.knowledge.state_document import (
    ACTIONS,
    STATE_FILE,
    StateDocument,
    StateError,
    section_diff,
)


class UpdateStateTool:
    name = "update_state"
    risk = "write"
    # Une phrase courte : avec une description longue, qwen3-coder écrivait ses
    # appels d'outils en texte (tous outils confondus, mesuré le 2026-10-17).
    # La façon de s'en servir est dans le prompt système (state_document.py).
    description = "Met à jour une section du document d'état du projet SENSAI.md."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "action": {"type": "string", "enum": list(ACTIONS)},
            "content": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["section", "action", "content"],
    }

    def __init__(self, document: StateDocument) -> None:
        self.document = document

    def describe_call(self, **args: Any) -> str:
        """Ce que l'utilisateur approuve : le changement de la section."""
        section = args.get("section", "")
        try:
            diff = self.document.preview(section, args.get("action", ""), args.get("content", ""))
        except StateError as e:
            return f"{STATE_FILE}, section « {section} » — sera refusé : {e}"
        return f"{STATE_FILE}, section « {section} » ({args.get('action')}) :\n{diff}"

    def run(self, **kwargs: Any) -> ToolResult:
        section = str(kwargs.get("section", ""))
        try:
            old, new = self.document.update(
                section, kwargs.get("action", ""), kwargs.get("content", ""), kwargs.get("summary")
            )
        except StateError as e:
            # Contrat Tool : jamais d'exception, l'agent doit pouvoir corriger son appel.
            return ToolResult(ok=False, content=str(e), data={"error": "invalid_update"})
        except OSError as e:
            return ToolResult(ok=False, content=f"Écriture impossible : {e.strerror}",
                              data={"error": "io"})
        return ToolResult(
            ok=True,
            content=f"{STATE_FILE} mis à jour, section « {section} » :\n"
            f"{section_diff(section, old, new)}",
            data={"section": section},
        )
