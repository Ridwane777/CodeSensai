"""
[Lot A — Fresnel] Sélection automatique d'exemples few-shot — feature [A7],
ADR-0044.

Le catalogue cite en exemple réel « des systèmes qui choisissent les
meilleurs exemples few-shot selon la requête entrante » (DSPy). C'est ce
qu'on fait ici : une petite bibliothèque d'exemples (question + bonne
réponse), et à chaque question posée, on cherche par similarité sémantique
l'exemple le plus proche pour le coller avant la question, comme une
démonstration de ce qu'est une bonne réponse.

Le fichier d'exemples réutilise le format des jeux de données d'évaluation
(feature EV1, `sensai.eval.dataset`) : un cas sans `answer` ne peut pas
servir de démonstration, donc il est ignoré ici plutôt que de planter.

Pas de framework LLM (ADR-0001) : les embeddings passent par le même
`Embedder` que le RAG (`knowledge/rag.py`), réutilisé tel quel.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sensai.eval.dataset import DatasetError, load_dataset
from sensai.knowledge.rag import Embedder, EmbeddingError

DEFAULT_MIN_SCORE = 0.75  # ESTIMATION, pas une mesure (ADR-0044) : plus strict que le RAG
# (0,54), car un mauvais exemple égare le modèle plus qu'un passage de code
# hors sujet, qu'on peut ignorer. À valider avec scripts/bench_fewshot.py.


class FewShotError(ValueError):
    """Fichier d'exemples illisible ou invalide : le message dit quoi faire."""


def _normalized(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


@dataclass(frozen=True)
class Example:
    question: str
    answer: str


class FewShotIndex:
    """Exemples embeddés une fois au chargement (petit fichier, pas de SQLite).

    Contrairement au RAG (`rag.py`), rien n'est persisté : un fichier
    d'exemples se recharge en un instant, et il change rarement en cours de
    session.
    """

    def __init__(self, embed: Embedder, min_score: float = DEFAULT_MIN_SCORE):
        self.embed = embed
        self.min_score = min_score
        self._examples: list[Example] = []
        self._matrix: np.ndarray | None = None

    def questions(self) -> list[str]:
        """Les questions des exemples chargés (l'interface web les affiche, A7)."""
        return [e.question for e in self._examples]

    def load(self, path: str | Path) -> int:
        """Charge les cas qui ont une réponse ; renvoie leur nombre.

        FewShotError si le fichier est illisible ou mal formé (même erreur
        que `sensai-eval`, pour que l'utilisateur la reconnaisse) ;
        EmbeddingError si Ollama est indisponible.
        """
        try:
            dataset = load_dataset(path)
        except DatasetError as e:
            raise FewShotError(str(e)) from e
        self._examples = [
            Example(question=c.question, answer=c.answer)
            for c in dataset.cases if c.answer
        ]
        if not self._examples:
            raise FewShotError(f"{path} : aucun cas avec une réponse (« answer ») à réutiliser")
        vectors = self.embed([e.question for e in self._examples])
        self._matrix = _normalized(vectors)
        return len(self._examples)

    def best_match(self, query: str) -> Example | None:
        """L'exemple le plus proche de `query`, ou None sous le seuil."""
        if self._matrix is None or not self._examples:
            return None
        q = _normalized(self.embed([query]))[0]
        if q.shape[0] != self._matrix.shape[1]:
            raise EmbeddingError(
                "les exemples few-shot ont été embeddés avec un autre modèle : "
                "relancer pour les recharger"
            )
        scores = self._matrix @ q
        best = int(np.argmax(scores))
        if scores[best] < self.min_score:
            return None
        return self._examples[best]


def _same_question(a: str, b: str) -> bool:
    """Même question, à la casse, à la ponctuation et aux espaces près."""
    def norm(s: str) -> str:
        return " ".join("".join(c if c.isalnum() else " " for c in s.lower()).split())
    return norm(a) == norm(b)


def worth_attaching(example: Example, question: str, preferences: Sequence[str] = ()) -> bool:
    """Faut-il joindre l'exemple ? Pas quand la question est celle de l'exemple et
    que l'utilisateur a des préférences : le modèle recopie alors la réponse de
    l'exemple et ignore les préférences, même rappelées à côté (essai réel du
    2026-11-01 après-midi, « réponds en anglais » perdu sur cette seule question).
    Sans préférence, recopier une bonne réponse est justement ce qu'on veut."""
    return not (preferences and _same_question(example.question, question))


def format_example(example: Example, preferences: Sequence[str] = ()) -> str:
    """Bloc ajouté avant la question de l'utilisateur (A7).

    Formulation prudente, comme `rag.format_context` : un modèle à qui l'on
    montre un exemple a tendance à le commenter ou à y répondre à sa place
    plutôt qu'à la vraie question (même défaut observé pour le RAG,
    docs/performance/R1-rag.md). Les préférences passent avant : essai réel du
    2026-11-01, un exemple en français l'a emporté sur « réponds en anglais » ;
    le même jour, sur une question presque identique, le modèle recopiait la
    réponse de l'exemple mot pour mot, en français.
    """
    return (
        "[Exemple d'une question similaire déjà bien traitée, pour t'inspirer du "
        "style et du niveau de détail — ne réponds pas à cet exemple, seulement à "
        "la question ci-dessous, et ne recopie pas sa réponse : écris la tienne. Les "
        "préférences de l'utilisateur (langue, ton, format) passent avant cet exemple.]\n"
        f"Question similaire : {example.question}\n"
        f"Bonne réponse : {example.answer}"
        # Rappelées ici, à côté de l'exemple : dans le prompt système seulement, elles
        # perdaient contre lui (essai réel du 2026-11-01, trois questions sur trois).
        + ("\n[Préférences de l'utilisateur, à appliquer à ta réponse : "
           + " ; ".join(preferences) + "]" if preferences else "")
    )
