"""
Construction du registre d'outils, partagée par toutes les interfaces.

La CLI interactive (`sensai`) et le planificateur (`sensai-schedule`, feature
X5) doivent proposer les mêmes outils : un outil enregistré ici arrive aux
deux, sans que personne ait à penser à le brancher à deux endroits. Ce qui
change entre eux, ce n'est pas le registre mais la politique de la passerelle
(confirmation par l'utilisateur d'un côté, refus systématique de l'autre).
"""
from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.tools.list_files_tool import ListFilesTool
from sensai.tools.read_file_tool import ReadFileTool
from sensai.tools.sandbox_tool import SandboxTool
from sensai.tools.web_search_tool import WebSearchTool
from sensai.tools.write_file_tool import WriteFileTool


def build_registry(permissions: FilePermissions | None = None) -> ToolRegistry:
    """Les lots B, C et D enregistreront leurs outils ici. Une ligne par outil :
    c'est le seul endroit que les quatre lots modifient, autant qu'il reste
    minuscule (voir CONTRIBUTING.md).

    Aucun outil ne contacte Docker à sa construction, seulement à son premier
    appel : le CLI démarre même sans Docker. `permissions` vient de la section
    `files` de config.json (ADR-0011) ; sans elle, le dossier courant."""
    registry = ToolRegistry()
    # Lot B : exécution isolée (T2), fichiers du dossier courant (T4), web (T3).
    registry.register(SandboxTool())
    registry.register(ReadFileTool(permissions))
    # Voir les fichiers du projet sans RAG (ADR-0059, essai du 2026-11-06).
    registry.register(ListFilesTool(permissions))
    registry.register(WriteFileTool(permissions))
    registry.register(WebSearchTool())
    return registry
