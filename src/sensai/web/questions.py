"""
[Lot D] Questions de l'agent depuis le navigateur — feature [X4] (ADR-0046).

Même mécanique que la confirmation web (`execution/web_confirmation.py`,
ADR-0015) : l'outil `ask_user` appelle un `Asker` SYNCHRONE, qui publie un
événement `question` dans le flux SSE et bloque le thread de l'agent jusqu'à
la réponse du navigateur (`POST /api/sessions/{id}/answer`).

Pas de réponse à temps, broker fermé (onglet fermé, interruption, fin du
tour) ou `emit` en panne : `None`, que l'outil transforme en « pas de
réponse ». Une réponse invalide (champ inconnu, mauvais type, choix absent)
est refusée sans réveiller l'agent : le navigateur peut la corriger.
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from sensai.tools.ask_user_tool import ANSWER_TIMEOUT_S, Question, check_answers

log = logging.getLogger(__name__)


class _Pending:
    __slots__ = ("event", "question", "values")

    def __init__(self, question: Question) -> None:
        self.event = threading.Event()
        self.question = question
        self.values: dict[str, Any] | None = None


class WebQuestionBroker:
    """Un broker par tour : relie l'outil `ask_user` à la réponse du navigateur."""

    def __init__(self, emit: Callable[[dict[str, Any]], None], *,
                 timeout_s: float = ANSWER_TIMEOUT_S) -> None:
        self._emit = emit
        self._timeout_s = timeout_s
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._closed = False

    def ask(self, question: Question) -> dict[str, Any] | None:
        """L'`Asker` de l'outil. Ne lève jamais."""
        question_id = "question_" + uuid.uuid4().hex
        entry = _Pending(question)
        try:
            with self._lock:
                if self._closed:
                    return None
                self._pending[question_id] = entry
            self._emit({"type": "question", "question_id": question_id,
                        "title": question.title, "fields": list(question.fields),
                        "timeout_s": self._timeout_s})
            entry.event.wait(self._timeout_s)
            with self._lock:
                return entry.values
        except Exception:
            log.exception("question web en échec : traitée comme sans réponse")
            return None
        finally:
            with self._lock:
                if self._pending.get(question_id) is entry:
                    del self._pending[question_id]

    def resolve(self, question_id: str, values: Any) -> str:
        """Donne la réponse du navigateur.

        Renvoie "ok", "unknown" (identifiant inconnu, déjà répondu ou expiré) ou
        le message d'erreur d'une réponse invalide (la question reste ouverte).
        """
        with self._lock:
            entry = self._pending.get(question_id)
            if entry is None:
                return "unknown"
            try:
                clean = check_answers(entry.question, values)
            except ValueError as e:
                return str(e)
            del self._pending[question_id]
            entry.values = clean
            entry.event.set()
            return "ok"

    def close(self) -> None:
        """Toutes les questions en attente deviennent « sans réponse »."""
        with self._lock:
            self._closed = True
            entries = list(self._pending.values())
            self._pending.clear()
        for entry in entries:
            entry.event.set()
