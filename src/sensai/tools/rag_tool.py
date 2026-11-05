"""
[Lot C — Ridwane] Expose la recherche RAG (knowledge/rag.py) comme un Tool
appelable par l'agent — feature [R1] Basic RAG.

Le CLI ajoute déjà automatiquement les passages pertinents à chaque question.
Cet outil sert à la boucle ReAct du Lot A : le modèle pourra chercher lui-même,
plusieurs fois et avec ses propres mots (ADR-0009, décision 4). Le CLI
l'enregistre sans index et le lui donne à la première question (ADR-0013).
"""
from __future__ import annotations

from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.knowledge.rag import (
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    EmbeddingError,
    RagIndex,
    format_search_results,
)


class RagTool:
    name = "search_codebase"
    # Lecture seule : la passerelle l'autorise sans confirmation (ADR-0006).
    risk = "read"
    description = (
        "Cherche dans le code et la documentation du projet les passages les plus "
        "proches d'une question, avec leur fichier et leurs lignes."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Ce qu'on cherche"},
            "kind": {"type": "string", "enum": ["code", "doc"],
                     "description": "Seulement le code, ou seulement la documentation"},
            "path": {"type": "string", "description": "Seulement ce dossier, ex. src/sensai"},
        },
        "required": ["query"],
    }

    def __init__(
        self,
        index: RagIndex | None = None,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = DEFAULT_MIN_SCORE,
    ):
        self.index = index
        self.top_k = top_k
        self.min_score = min_score

    def run(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, content="Requête vide : précise ce qu'il faut chercher.")
        if self.index is None:
            return ToolResult(ok=False, content="Recherche indisponible : projet non indexé.")
        try:
            # Filtres de R2 (US-R2-2) : une valeur inconnue est ignorée, pas refusée.
            kind = kwargs.get("kind") if kwargs.get("kind") in ("code", "doc") else None
            path = str(kwargs.get("path") or "").strip() or None
            hits = self.index.search(query, top_k=self.top_k, min_score=self.min_score,
                                     kind=kind, path=path)
        except EmbeddingError as e:
            # Contrat Tool : jamais d'exception, l'agent doit pouvoir continuer.
            return ToolResult(ok=False, content=f"Recherche impossible : {e}")
        content = format_search_results(query, hits)
        return ToolResult(ok=True, content=content, data={"passages": hits})
