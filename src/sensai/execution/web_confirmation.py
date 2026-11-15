"""
[Workstream B - Meric] Confirmation from the browser - feature [A3] Human-in-the-Loop,
web version (issue #47).

Cross-workstream contract (ADR-0005, ADR-0006): the gateway calls a
SYNCHRONOUS `Confirmer`, `(ConfirmationRequest) -> bool`. `human_in_loop.py`
provides the CLI one; this module provides the web one, without touching the
gateway (ADR-0015). It depends on no framework, only `threading`. Workstream D
wires `emit` (push an event into the SSE stream) and calls `resolve` from its
`POST /sessions/{id}/confirm` route. "To be wired by Workstream D": see
docs/architecture/web/web-api.md.

Rule: only `approved is True` allows. Timeout, closed broker (tab closed,
session ended), failing `emit`, unknown id: refusal. The confirmer never
raises, and never leaves a request pending.

The confirmer BLOCKS its calling thread until the answer: the agent must
therefore run in a worker thread, not in the event loop.
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from .gateway import ConfirmationRequest
from .tool_policy import Risk

log = logging.getLogger(__name__)


class _Pending:
    """A pending request: the event that wakes the confirmer, and the answer."""

    __slots__ = ("approved", "event")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.approved = False


def _new_id() -> str:
    return "confirm_" + uuid.uuid4().hex


class WebConfirmationBroker:
    """Connects the gateway's blocking confirmer to an answer from the web.

    One broker per session. `emit` receives the dict to send to the browser
    (type `confirm_request`); it is called from the agent thread, outside any
    lock, and must therefore be thread-safe (e.g.
    `loop.call_soon_threadsafe(queue.put_nowait, payload)`).
    """

    def __init__(
        self,
        emit: Callable[[dict[str, Any]], None],
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._emit = emit
        self._id_factory = id_factory or _new_id
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._closed = False

    # -- gateway side ---------------------------------------------------------

    @property
    def confirmer(self) -> Callable[[ConfirmationRequest], bool]:
        """The `Confirmer` to pass to `ToolGateway(confirm=...)`."""
        return self._confirm

    def make_confirmer(self) -> Callable[[ConfirmationRequest], bool]:
        return self._confirm

    def _confirm(self, request: ConfirmationRequest) -> bool:
        """Publish the request, wait at most `request.timeout_s`. Never raises."""
        confirm_id: str | None = None
        entry = _Pending()
        try:
            confirm_id = self._id_factory()
            with self._lock:
                if self._closed:
                    return False
                if confirm_id in self._pending:
                    # Id collision: answering the wrong request would be worse
                    # than a refusal.
                    log.error("confirmation id already in use: refused")
                    confirm_id = None
                    return False
                self._pending[confirm_id] = entry
            # Outside the lock: an `emit` that answers at once (or takes time)
            # must neither block `resolve`/`close` nor cause a deadlock.
            self._emit(
                {
                    "type": "confirm_request",
                    "id": confirm_id,
                    "tool": request.tool,
                    "risk": Risk(request.risk).value,
                    "summary": request.summary,
                    "arguments": request.arguments,
                    "timeout_s": request.timeout_s,
                }
            )
            entry.event.wait(request.timeout_s)
            with self._lock:
                # An answer arriving at the very last moment still counts:
                # `resolve` wrote `approved` under this same lock.
                return entry.approved is True
        except Exception:
            log.exception("web confirmation failed: treated as a refusal")
            return False
        finally:
            if confirm_id is not None:
                with self._lock:
                    if self._pending.get(confirm_id) is entry:
                        del self._pending[confirm_id]

    # -- web side ---------------------------------------------------------------

    def resolve(self, confirm_id: str, approved: object) -> bool:
        """Deliver the browser's answer. True only if a pending request matches.

        Only `approved is True` allows (not `1`, not `"true"`). Unknown,
        already answered or expired id: `False`, no exception; the first
        answer wins.
        """
        if not isinstance(confirm_id, str):
            return False
        with self._lock:
            entry = self._pending.pop(confirm_id, None)
            if entry is None:
                return False
            entry.approved = approved is True
            entry.event.set()
            return True

    def pending_ids(self) -> list[str]:
        """Ids of the requests still waiting for an answer."""
        with self._lock:
            return list(self._pending)

    def close(self) -> None:
        """Refuse every pending request; later ones are refused without `emit`.

        Call it when the browser disconnects or the session ends.
        """
        with self._lock:
            self._closed = True
            entries = list(self._pending.values())
            self._pending.clear()
        for entry in entries:
            entry.approved = False
            entry.event.set()
