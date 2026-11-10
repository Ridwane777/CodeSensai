"""
[Workstream D] Agent questions from the browser — feature [X4] (ADR-0046).

Same mechanism as web confirmation (`execution/web_confirmation.py`,
ADR-0015): the `ask_user` tool calls a SYNCHRONOUS `Asker`, which publishes a
`question` event on the SSE stream and blocks the agent thread until the
browser answers (`POST /api/sessions/{id}/answer`).

No answer in time, broker closed (tab closed, interruption, end of turn) or
`emit` failing: `None`, which the tool turns into "no answer". An invalid
answer (unknown field, wrong type, missing choice) is rejected without waking
the agent: the browser can correct it.
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
    """One broker per turn: connects the `ask_user` tool to the browser's answer."""

    def __init__(self, emit: Callable[[dict[str, Any]], None], *,
                 timeout_s: float = ANSWER_TIMEOUT_S) -> None:
        self._emit = emit
        self._timeout_s = timeout_s
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._closed = False

    def ask(self, question: Question) -> dict[str, Any] | None:
        """The tool's `Asker`. Never raises."""
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
            log.exception("web question failed: treated as unanswered")
            return None
        finally:
            with self._lock:
                if self._pending.get(question_id) is entry:
                    del self._pending[question_id]

    def resolve(self, question_id: str, values: Any) -> str:
        """Delivers the browser's answer.

        Returns "ok", "unknown" (unknown id, already answered or expired) or
        the error message of an invalid answer (the question stays open).
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
        """All pending questions become "unanswered"."""
        with self._lock:
            self._closed = True
            entries = list(self._pending.values())
            self._pending.clear()
        for entry in entries:
            entry.event.set()
