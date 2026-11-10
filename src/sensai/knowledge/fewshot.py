"""
[Workstream A — Fresnel] Automatic few-shot example selection — feature [A7],
ADR-0044.

The feature catalog cites as a real-world example "systems that pick the best
few-shot examples for the incoming request" (DSPy). That is what this does: a
small library of examples (question + good answer), and for each question
asked, the closest example is found by semantic similarity and placed before
the question, as a demonstration of what a good answer looks like.

The example file reuses the evaluation dataset format (feature EV1,
`sensai.eval.dataset`): a case without `answer` cannot serve as a
demonstration, so it is skipped here rather than crashing.

No LLM framework (ADR-0001): embeddings go through the same `Embedder` as RAG
(`knowledge/rag.py`), reused as is.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sensai.eval.dataset import DatasetError, load_dataset
from sensai.knowledge.rag import Embedder, EmbeddingError

DEFAULT_MIN_SCORE = 0.75  # ESTIMATE, not a measurement (ADR-0044): stricter than RAG
# (0.54), because a bad example misleads the model more than an off-topic code
# passage, which it can ignore. To be validated with scripts/bench_fewshot.py.


class FewShotError(ValueError):
    """Unreadable or invalid example file: the message says what to do."""


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
    """Examples embedded once at load time (small file, no SQLite).

    Unlike RAG (`rag.py`), nothing is persisted: an example file reloads in an
    instant, and it rarely changes during a session.
    """

    def __init__(self, embed: Embedder, min_score: float = DEFAULT_MIN_SCORE):
        self.embed = embed
        self.min_score = min_score
        self._examples: list[Example] = []
        self._matrix: np.ndarray | None = None

    def questions(self) -> list[str]:
        """The questions of the loaded examples (shown by the web interface, A7)."""
        return [e.question for e in self._examples]

    def load(self, path: str | Path) -> int:
        """Load the cases that have an answer; return how many.

        FewShotError if the file is unreadable or malformed (same error as
        `sensai-eval`, so the user recognizes it); EmbeddingError if Ollama is
        unavailable.
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
            raise FewShotError(f"{path}: no case with an answer (\"answer\") to reuse")
        vectors = self.embed([e.question for e in self._examples])
        self._matrix = _normalized(vectors)
        return len(self._examples)

    def best_match(self, query: str) -> Example | None:
        """The example closest to `query`, or None below the threshold."""
        if self._matrix is None or not self._examples:
            return None
        q = _normalized(self.embed([query]))[0]
        if q.shape[0] != self._matrix.shape[1]:
            raise EmbeddingError(
                "the few-shot examples were embedded with a different model: "
                "restart to reload them"
            )
        scores = self._matrix @ q
        best = int(np.argmax(scores))
        if scores[best] < self.min_score:
            return None
        return self._examples[best]


def _same_question(a: str, b: str) -> bool:
    """Same question, ignoring case, punctuation and whitespace."""
    def norm(s: str) -> str:
        return " ".join("".join(c if c.isalnum() else " " for c in s.lower()).split())
    return norm(a) == norm(b)


def worth_attaching(example: Example, question: str, preferences: Sequence[str] = ()) -> bool:
    """Should the example be attached? Not when the question is the example's own and
    the user has preferences: the model then copies the example's answer and
    ignores the preferences, even when restated next to it (real trial run of
    2026-11-01 afternoon, "answer in English" lost on that one question).
    Without preferences, copying a good answer is exactly what we want."""
    return not (preferences and _same_question(example.question, question))


def format_example(example: Example, preferences: Sequence[str] = ()) -> str:
    """Block added before the user's question (A7).

    Careful wording, like `rag.format_context`: a model shown an example tends
    to comment on it or answer it instead of the real question (same flaw seen
    with RAG, docs/performance/R1-rag.md). Preferences come first: in the real
    trial run of 2026-11-01, a French example won over "answer in English"; the
    same day, on an almost identical question, the model copied the example's
    answer word for word, in French.
    """
    return (
        "[Example of a similar question already answered well, to guide your "
        "style and level of detail — do not answer this example, only the question "
        "below, and do not copy its answer: write your own. The user preferences "
        "(language, tone, format) take precedence over this example.]\n"
        f"Similar question: {example.question}\n"
        f"Good answer: {example.answer}"
        # Restated here, next to the example: in the system prompt alone, they lost
        # against it (real trial run of 2026-11-01, three questions out of three).
        + ("\n[User preferences, to apply to your answer: "
           + "; ".join(preferences) + "]" if preferences else "")
    )
