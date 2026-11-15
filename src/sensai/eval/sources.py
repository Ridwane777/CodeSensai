"""
Reference passages the judge compares with the answer - feature [EV1], ADR-0019.

The judge knows nothing about the world: it says "supported" only if a supplied
passage says so. Where these passages come from is a provider concern
(`SourceProvider`), so the tests need neither Ollama nor an index:

- `static_sources`: texts written in the dataset (deterministic);
- `rag_sources`:    any object with `.search(query, top_k, min_score)`,
                    in practice the R1 `RagIndex`.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

DEFAULT_SOURCE_LABEL = "dataset"
NO_PASSAGES = "(no passage supplied)"


@dataclass(frozen=True)
class Passage:
    """A numbered passage; `id` ("S1", "S2"…) is what the judge must cite."""

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
    """Hand-written passages: a string, or `{"source": ..., "text": ...}`."""
    passages = []
    for n, item in enumerate(items, start=1):
        if isinstance(item, str):
            source, text = DEFAULT_SOURCE_LABEL, item
        else:
            source, text = str(item.get("source") or DEFAULT_SOURCE_LABEL), str(item["text"])
        passages.append(Passage(id=f"S{n}", source=source, text=text))
    return passages


def rag_sources(index: Any, top_k: int, min_score: float) -> SourceProvider:
    """Provider that queries a search index (R1) with the question.

    `index.search(query, top_k=, min_score=)` returns dicts
    `{source, start, end, text, score}`. An index that finds nothing above the
    threshold returns an empty list: the judge will see "no passage".
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
    """`[S1] file:start-end` then the text, one block per passage."""
    if not passages:
        return NO_PASSAGES
    return "\n\n".join(f"[{p.id}] {p.location()}\n{p.text}" for p in passages)
