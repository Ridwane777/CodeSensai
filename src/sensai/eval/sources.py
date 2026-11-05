"""
Passages de référence que le juge compare à la réponse — feature [EV1], ADR-0019.

Le juge ne connaît rien du monde : il ne dit « soutenu » que si un passage
fourni le dit. D'où viennent ces passages est une affaire de fournisseur
(`SourceProvider`), pour que les tests n'aient besoin ni d'Ollama ni d'index :

- `static_sources` : textes écrits dans le jeu de données (déterministe) ;
- `rag_sources`    : n'importe quel objet qui a `.search(query, top_k, min_score)`,
                     en pratique le `RagIndex` de R1.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

DEFAULT_SOURCE_LABEL = "dataset"
NO_PASSAGES = "(aucun passage fourni)"


@dataclass(frozen=True)
class Passage:
    """Un passage numéroté ; `id` ("S1", "S2"…) est ce que le juge doit citer."""

    id: str
    source: str
    text: str
    start: int | None = None
    end: int | None = None

    def location(self) -> str:
        if self.start is None or self.end is None:
            return self.source
        return f"{self.source}:{self.start}-{self.end}"

    def citation(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source, "start": self.start, "end": self.end}


SourceProvider = Callable[[str], list[Passage]]


def static_sources(items: Iterable[str | dict[str, Any]]) -> list[Passage]:
    """Passages écrits à la main : une chaîne, ou `{"source": ..., "text": ...}`."""
    passages = []
    for n, item in enumerate(items, start=1):
        if isinstance(item, str):
            source, text = DEFAULT_SOURCE_LABEL, item
        else:
            source, text = str(item.get("source") or DEFAULT_SOURCE_LABEL), str(item["text"])
        passages.append(Passage(id=f"S{n}", source=source, text=text))
    return passages


def rag_sources(index: Any, top_k: int, min_score: float) -> SourceProvider:
    """Fournisseur qui interroge un index de recherche (R1) avec la question.

    `index.search(query, top_k=, min_score=)` renvoie des dicts
    `{source, start, end, text, score}`. Un index qui ne trouve rien sous le
    seuil renvoie une liste vide : le juge verra « aucun passage ».
    """

    def provider(question: str) -> list[Passage]:
        hits = index.search(question, top_k=top_k, min_score=min_score)
        return [
            Passage(
                id=f"S{n}",
                source=hit["source"],
                text=hit["text"],
                start=hit.get("start"),
                end=hit.get("end"),
            )
            for n, hit in enumerate(hits, start=1)
        ]

    return provider


def format_passages(passages: list[Passage]) -> str:
    """`[S1] fichier:début-fin` puis le texte, un bloc par passage."""
    if not passages:
        return NO_PASSAGES
    return "\n\n".join(f"[{p.id}] {p.location()}\n{p.text}" for p in passages)
