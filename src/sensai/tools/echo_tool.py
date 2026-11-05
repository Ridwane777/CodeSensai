"""
Outil de démonstration — implémente le contrat Tool (core/tools.py).

Sert de gabarit pour sandbox_tool.py et rag_tool.py, et permet de tester le
ToolRegistry et la future boucle ReAct avant que les vrais outils soient prêts.
"""
from typing import Any, ClassVar

from sensai.core.tools import ToolResult


class EchoTool:
    name = "echo"
    description = "Renvoie le texte reçu tel quel. Sert à tester le registre d'outils."
    # Obligatoire pour la passerelle (docs/architecture/tool-contract.md) : un outil sans
    # risque déclaré est traité comme le plus dangereux et demande confirmation.
    risk = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def run(self, **kwargs) -> ToolResult:
        text = kwargs.get("text", "")
        return ToolResult(ok=True, content=text)
