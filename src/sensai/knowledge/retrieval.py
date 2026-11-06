"""
[Lot C — Ridwane] Recherche par mots et fusion des classements — feature [R2].

`BM25` complète la recherche par embeddings de R1 : les noms du code
(`retention_days`, `purge`, `SessionStore`) sont des mots exacts, que les
embeddings rapprochent mal. `reciprocal_rank_fusion` combine les deux
classements par leurs rangs (Cormack, Clarke et Büttcher, SIGIR 2009), sans
avoir à rendre leurs scores comparables. Choix et mesures : ADR-0032.

BM25 et la fusion n'utilisent que la bibliothèque standard : une dépendance
(rank_bm25) n'apporterait rien. `LlmReranker` demande ensuite au modèle de
chat de reclasser les premiers passages (Ollama n'a pas de `/api/rerank`).
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

# Mots trop fréquents pour aider à trouver un passage (français et anglais).
STOPWORDS = frozenset("""
le la les un une des du de d l au aux et ou en dans sur par pour avec sans ce cet cette
ces qui que quoi dont où est sont a ont être avoir fait faire il elle ils elles on se
sa son ses leur leurs ne pas plus comme mais si y à quel quelle quels quelles comment
pourquoi quand combien doit peut the a an of to in is are and or for on with by be as
it this that from at not
""".split())

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokenize(text: str) -> list[str]:
    """Mots en minuscules, sans accents, `snake_case` et `CamelCase` découpés,
    en gardant aussi le nom entier (`retention_days`, `retention`, `days`)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    tokens: list[str] = []
    for whole in re.findall(r"[A-Za-z0-9_]+", text):
        parts = [p for chunk in whole.split("_") for p in _CAMEL.split(chunk) if p]
        if len(parts) > 1:
            tokens.append(whole.lower())
        tokens.extend(p.lower() for p in parts)
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


class BM25:
    """Okapi BM25 sur une liste de documents (k1 = 1,2 ; b = 0,75)."""

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
        """(index du document, score), du meilleur au moins bon ; scores nuls exclus."""
        ranked = sorted(enumerate(self.scores(query)), key=lambda p: -p[1])
        return [(i, s) for i, s in ranked[:top_k] if s > 0]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[dict[str, Any]]],
    key: Callable[[dict[str, Any]], Hashable],
    k: int = 60,
) -> list[dict[str, Any]]:
    """Fusionne des classements : score = somme de 1 / (k + rang) sur chacun.

    Le premier dict rencontré pour une clé est gardé (avec ses champs) ; son
    score de fusion est dans `fusion`.
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
    "Question : {question}\n\nPassages numérotés :\n{passages}\n\n"
    "Classe les numéros des passages du plus utile au moins utile pour répondre à la "
    "question. Réponds seulement en JSON : {{\"ordre\": [numéros]}}."
)


class LlmReranker:
    """Le modèle de chat reclasse les `depth` premiers passages, en un seul appel.

    Mesuré avec le vrai modèle (ADR-0032) : le bon fichier passe de 5 à 12 fois sur 15
    en première position, pour environ 3 s de plus. En cas d'échec (Ollama
    injoignable, JSON invalide), l'ordre reçu est rendu tel quel : le
    reclassement améliore la recherche, il ne doit jamais la casser.
    """

    def __init__(self, host: str, model: str, depth: int = RERANK_DEPTH,
                 timeout: float = 60, num_ctx: int | None = None) -> None:
        self.host, self.model, self.depth, self.timeout = host, model, depth, timeout
        # M2, ADR-0045 : sans num_ctx, Ollama tronque en silence le prompt de
        # reclassement (jusqu'à `depth` passages de 600 caractères).
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
        # Température 0 : un classement doit être reproductible (ADR-0057) ; il ne suit
        # pas les paramètres de génération de la conversation.
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
