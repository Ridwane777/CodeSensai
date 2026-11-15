"""
[Workstream C - Ridwane] Keyword search and rank fusion - feature [R2].

`BM25` complements R1's embedding search: code names (`retention_days`,
`purge`, `SessionStore`) are exact words that embeddings match poorly.
`reciprocal_rank_fusion` combines both rankings by rank (Cormack, Clarke and
Büttcher, SIGIR 2009), without having to make their scores comparable.
Choices and measurements: ADR-0032.

BM25 and the fusion use only the standard library: a dependency (rank_bm25)
would add nothing. `LlmReranker` then asks the chat model to rerank the top
passages (Ollama has no `/api/rerank`).
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Hashable, Sequence
from typing import Any

import requests

# Words too frequent to help find a passage (French and English).
STOPWORDS = frozenset("""
le la les un une des du de d l au aux et ou en dans sur par pour avec sans ce cet cette
ces qui que quoi dont où est sont a ont être avoir fait faire il elle ils elles on se
sa son ses leur leurs ne pas plus comme mais si y à quel quelle quels quelles comment
pourquoi quand combien doit peut the a an of to in is are and or for on with by be as
it this that from at not
""".split())

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokenize(text: str) -> list[str]:
    """Lowercase words, accents stripped, `snake_case` and `CamelCase` split,
    also keeping the whole name (`retention_days`, `retention`, `days`)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    tokens: list[str] = []
    for whole in re.findall(r"[A-Za-z0-9_]+", text):
        parts = [p for chunk in whole.split("_") for p in _CAMEL.split(chunk) if p]
        if len(parts) > 1:
            tokens.append(whole.lower())
        tokens.extend(p.lower() for p in parts)
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


class BM25:
    """Okapi BM25 over a list of documents (k1 = 1.2; b = 0.75)."""

    def __init__(self, documents: Sequence[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(d)) for d in documents]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.average = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        frequency: Counter[str] = Counter()
        for counts in self.docs:
            frequency.update(counts.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequency.items()}

    def scores(self, query: str) -> list[float]:
        terms = [t for t in set(tokenize(query)) if t in self.idf]
        result = []
        for counts, length in zip(self.docs, self.lengths, strict=True):
            norm = self.k1 * (1 - self.b + self.b * length / self.average) if self.average else 0
            result.append(sum(
                self.idf[t] * counts[t] * (self.k1 + 1) / (counts[t] + norm)
                for t in terms if counts[t]
            ))
        return result

    def search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        """(document index, score), best first; zero scores excluded."""
        ranked = sorted(enumerate(self.scores(query)), key=lambda p: -p[1])
        return [(i, s) for i, s in ranked[:top_k] if s > 0]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[dict[str, Any]]],
    key: Callable[[dict[str, Any]], Hashable],
    k: int = 60,
) -> list[dict[str, Any]]:
    """Fuses rankings: score = sum of 1 / (k + rank) over each.

    The first dict seen for a key is kept (with its fields); its fusion
    score is in `fusion`.
    """
    fused: dict[Hashable, float] = {}
    items: dict[Hashable, dict[str, Any]] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            ident = key(item)
            fused[ident] = fused.get(ident, 0.0) + 1 / (k + rank)
            items.setdefault(ident, item)
    order = sorted(fused, key=lambda ident: -fused[ident])
    return [items[ident] | {"fusion": round(fused[ident], 5)} for ident in order]


RERANK_DEPTH = 10
RERANK_PROMPT = (
    "Question: {question}\n\nNumbered passages:\n{passages}\n\n"
    "Rank the passage numbers from most to least useful for answering the "
    "question. Reply only in JSON: {{\"ordre\": [numbers]}}."
)


class LlmReranker:
    """The chat model reranks the top `depth` passages in a single call.

    Measured with the real model (ADR-0032): the right file goes from 5 to 12
    times out of 15 in first position, for about 3 s more. On failure (Ollama
    unreachable, invalid JSON), the received order is returned unchanged:
    reranking improves search, it must never break it.
    """

    def __init__(self, host: str, model: str, depth: int = RERANK_DEPTH,
                 timeout: float = 60, num_ctx: int | None = None) -> None:
        self.host, self.model, self.depth, self.timeout = host, model, depth, timeout
        # M2, ADR-0045: without num_ctx, Ollama silently truncates the rerank
        # prompt (up to `depth` passages of 600 characters).
        self.num_ctx = num_ctx

    def __call__(self, question: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        head, tail = hits[:self.depth], hits[self.depth:]
        if len(head) < 2:
            return hits
        passages = "\n\n".join(
            f"[{n}] {h['source']}\n{h['text'][:600]}" for n, h in enumerate(head))
        payload: dict[str, Any] = {
            "model": self.model, "stream": False, "format": "json",
            "messages": [{"role": "user", "content": RERANK_PROMPT.format(
                question=question, passages=passages)}],
        }
        # Temperature 0: a ranking must be reproducible (ADR-0057); it does not follow
        # the conversation's generation parameters.
        payload["options"] = {"temperature": 0}
        if self.num_ctx:
            payload["options"]["num_ctx"] = self.num_ctx
        try:
            response = requests.post(f"{self.host}/api/chat", json=payload,
                                     timeout=self.timeout)
            response.raise_for_status()
            order = [int(n) for n in json.loads(response.json()["message"]["content"])["ordre"]]
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return hits
        seen: list[int] = []
        for n in order:
            if 0 <= n < len(head) and n not in seen:
                seen.append(n)
        seen += [n for n in range(len(head)) if n not in seen]
        return [head[n] for n in seen] + tail
