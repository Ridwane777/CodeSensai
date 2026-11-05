"""
[Lot B — Méric] Confirmation depuis le navigateur — feature [A3] Human-in-the-Loop,
version web (issue #47).

Contrat inter-lots (ADR-0005, ADR-0006) : la passerelle appelle un `Confirmer`
SYNCHRONE, `(ConfirmationRequest) -> bool`. `human_in_loop.py` fournit celui de
la CLI ; ce module fournit celui du web, sans toucher à la passerelle
(ADR-0015). Il ne dépend d'aucun framework : seulement `threading`. C'est le
Lot D qui branche `emit` (pousser un événement dans le flux SSE) et qui appelle
`resolve` depuis sa route `POST /sessions/{id}/confirm`. « À brancher par le
Lot D » : voir docs/architecture/web/web-api.md.

Règle : seul `approved is True` autorise. Délai dépassé, broker fermé (onglet
fermé, session terminée), `emit` en panne, identifiant inconnu : refus. Le
confirmeur ne lève jamais, et ne laisse jamais de demande en attente.

Le confirmeur BLOQUE le thread qui l'appelle jusqu'à la réponse : l'agent doit
donc tourner dans un thread de travail, pas dans la boucle d'événements.
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
    """Une demande en attente : l'événement qui réveille le confirmeur et la réponse."""

    __slots__ = ("approved", "event")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.approved = False


def _new_id() -> str:
    return "confirm_" + uuid.uuid4().hex


class WebConfirmationBroker:
    """Relie le confirmeur bloquant de la passerelle à une réponse venue du web.

    Un broker par session. `emit` reçoit le dictionnaire à envoyer au
    navigateur (type `confirm_request`) ; il est appelé depuis le thread de
    l'agent, hors de tout verrou, et doit donc être sûr entre threads (ex.
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

    # -- côté passerelle ------------------------------------------------------

    @property
    def confirmer(self) -> Callable[[ConfirmationRequest], bool]:
        """Le `Confirmer` à passer à `ToolGateway(confirm=...)`."""
        return self._confirm

    def make_confirmer(self) -> Callable[[ConfirmationRequest], bool]:
        return self._confirm

    def _confirm(self, request: ConfirmationRequest) -> bool:
        """Publie la demande, attend au plus `request.timeout_s`. Ne lève jamais."""
        confirm_id: str | None = None
        entry = _Pending()
        try:
            confirm_id = self._id_factory()
            with self._lock:
                if self._closed:
                    return False
                if confirm_id in self._pending:
                    # Collision d'identifiant : répondre à la mauvaise demande
                    # serait pire qu'un refus.
                    log.error("identifiant de confirmation déjà utilisé : refus")
                    confirm_id = None
                    return False
                self._pending[confirm_id] = entry
            # Hors du verrou : un `emit` qui répond tout de suite (ou qui prend
            # du temps) ne doit ni bloquer `resolve`/`close` ni provoquer
            # d'interblocage.
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
                # Une réponse arrivée pile au dernier instant reste valable :
                # `resolve` a écrit `approved` sous ce même verrou.
                return entry.approved is True
        except Exception:
            log.exception("confirmation web en échec : traité comme un refus")
            return False
        finally:
            if confirm_id is not None:
                with self._lock:
                    if self._pending.get(confirm_id) is entry:
                        del self._pending[confirm_id]

    # -- côté web ----------------------------------------------------------------

    def resolve(self, confirm_id: str, approved: object) -> bool:
        """Donne la réponse du navigateur. Vrai seulement si une demande en attente correspond.

        Seul `approved is True` autorise (pas `1`, pas `"true"`). Identifiant
        inconnu, déjà répondu ou expiré : `False`, sans exception ; la première
        réponse l'emporte.
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
        """Identifiants des demandes qui attendent encore une réponse."""
        with self._lock:
            return list(self._pending)

    def close(self) -> None:
        """Refuse toutes les demandes en attente ; les suivantes sont refusées sans `emit`.

        À appeler quand le navigateur se déconnecte ou que la session finit.
        """
        with self._lock:
            self._closed = True
            entries = list(self._pending.values())
            self._pending.clear()
        for entry in entries:
            entry.approved = False
            entry.event.set()
