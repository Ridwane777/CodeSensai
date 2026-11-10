"""
[Workstream C — Ridwane] Exposes RAG search (knowledge/rag.py) as a Tool
the agent can call — feature [R1] Basic RAG.

The CLI already adds the relevant passages to every question automatically.
This tool serves Workstream A's ReAct loop: the model can search by itself,
several times and in its own words (ADR-0009, decision 4). The CLI registers
it without an index and hands it one on the first question (ADR-0013).
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
    # Read-only: the gateway allows it without confirmation (ADR-0006).
    risk = "read"
    description = (
        "Searches the project's code and documentation for the passages closest "
        "to a question, with their file and lines."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for"},
            "kind": {"type": "string", "enum": ["code", "doc"],
                     "description": "Only code, or only documentation"},
            "path": {"type": "string", "description": "Only this directory, e.g. src/sensai"},
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
            return ToolResult(ok=False, content="Empty query: say what to search for.")
        if self.index is None:
            return ToolResult(ok=False, content="Search unavailable: project not indexed.")
        try:
            # R2 filters (US-R2-2): an unknown value is ignored, not rejected.
            kind = kwargs.get("kind") if kwargs.get("kind") in ("code", "doc") else None
            path = str(kwargs.get("path") or "").strip() or None
            hits = self.index.search(query, top_k=self.top_k, min_score=self.min_score,
                                     kind=kind, path=path)
        except EmbeddingError as e:
            # Tool contract: never raise, the agent must be able to continue.
            return ToolResult(ok=False, content=f"Search failed: {e}")
        content = format_search_results(query, hits)
        return ToolResult(ok=True, content=content, data={"passages": hits})
