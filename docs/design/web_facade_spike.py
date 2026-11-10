"""
FastAPI web facade prototype on top of the core (ADR-0022, ADR-0023): an example, not the final server.

What this file shows, which the docs/architecture/web/web-api.md skeleton could not:

- the core is SYNCHRONOUS (`run_agent_turn` is a blocking generator, confirmation is a blocking
  function): so the agent runs in a thread, and its events reach the asyncio loop through a queue;
  the confirmer waits for the browser's answer with a `threading.Event`;
- the confirmer is an ordinary function, not a coroutine: the gateway requires `is True`, and a
  returned coroutine would always be refused;
- no answer before the timeout, browser disconnection or interruption = refusal, never acceptance;
- one turn at a time per session, several sessions in parallel without mixing;
- every API route requires a token, except /api/health.

Dependencies NOT declared in requirements.txt: fastapi, uvicorn (and httpx for the tests).
It is not wired into the application; the test is in tests/web/test_web_facade_spike.py.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sensai.core.agent import ToolCaller, run_agent_turn
from sensai.core.events import Done, Event, Token, to_wire
from sensai.execution.gateway import ConfirmationRequest, Confirmer

log = logging.getLogger("sensai.web")

MAX_MESSAGE_CHARS = 20_000
EXPIRY_MARGIN_S = 0.1

GatewayFactory = Callable[[Confirmer], ToolCaller]
TurnRunner = Callable[[str, str, list[dict], ToolCaller], Iterator[Event]]


@dataclass
class Pending:
    """A confirmation waiting for the browser's answer."""

    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


@dataclass
class Session:
    id: str
    turns: list[dict] = field(default_factory=list)  # seulement user / assistant, comme History
    busy: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    pending: dict[str, Pending] = field(default_factory=dict)


class MessageIn(BaseModel):
    content: str


class ConfirmIn(BaseModel):
    confirm_id: str
    approved: bool


def error_body(code: str, error: str, details: str = "") -> dict[str, str]:
    return {"error": error, "code": code, "details": details}


def make_confirmer(session: Session, emit: Callable[[dict | None], None]) -> Confirmer:
    """Confirmeur web : publie un `confirm_request` dans le flux, puis attend POST /confirm.

    Called by the gateway in its own thread, with a timeout it sets. The same timeout is honoured here
    so no thread stays alive after a refusal, and "yes" is returned only if the browser said so
    explicitly, in time, without interruption.
    """

    def confirm(request: ConfirmationRequest) -> bool:
        confirm_id = uuid.uuid4().hex[:12]
        pending = Pending()
        session.pending[confirm_id] = pending
        try:
            emit(
                {
                    "type": "confirm_request",
                    "confirm_id": confirm_id,
                    "tool": request.tool,
                    "risk": getattr(request.risk, "value", str(request.risk)),
                    "summary": request.summary,
                    "arguments": request.arguments,
                    "timeout_s": request.timeout_s,
                }
            )
            # Expire slightly BEFORE the gateway: otherwise, in the few milliseconds where the gateway has
            # already refused but this confirmation still exists, a late answer would get "204" although
            # it has no effect any more. With this margin it gets "404", which is the truth.
            deadline = time.monotonic() + max(0.0, request.timeout_s - EXPIRY_MARGIN_S)
            while not pending.event.wait(0.05):
                if session.cancel.is_set() or time.monotonic() >= deadline:
                    return False
            return pending.approved is True and not session.cancel.is_set()
        finally:
            # A late answer will find no entry: 404, nothing runs.
            session.pending.pop(confirm_id, None)

    return confirm


def run_turn_in_thread(
    session: Session,
    content: str,
    emit: Callable[[dict | None], None],
    *,
    run_turn: TurnRunner,
    make_gateway: GatewayFactory,
    host: str,
    model: str,
    system_prompt: str,
) -> None:
    """Runs an agent turn outside the asyncio loop and publishes its events."""
    messages = [
        {"role": "system", "content": system_prompt},
        *session.turns,
        {"role": "user", "content": content},
    ]
    answer: list[str] = []
    reason = "error"
    interrupted = False
    generator = run_turn(host, model, messages, make_gateway(make_confirmer(session, emit)))
    try:
        for event in generator:
            if session.cancel.is_set():
                interrupted = True
                break
            if isinstance(event, Token):
                answer.append(event.text)
            if isinstance(event, Done):
                reason = event.reason
            emit(to_wire(event))
        if interrupted:
            emit({"type": "done", "reason": "interrupted"})
    except Exception:  # a core bug must neither leave the stream open nor leak a traceback
        log.exception("agent turn failed")
        emit({"type": "error", "message": "Erreur interne du serveur."})
        emit({"type": "done", "reason": "error"})
    finally:
        generator.close()
        # An interrupted or failed turn does not enter the history: no half turns.
        if reason == "final_answer" and not interrupted:
            session.turns += [
                {"role": "user", "content": content},
                {"role": "assistant", "content": "".join(answer)},
            ]
        session.busy = False
        emit(None)  # fin du flux


def create_app(
    *,
    token: str,
    make_gateway: GatewayFactory,
    host: str = "http://127.0.0.1:11434",
    model: str = "qwen3:8b",
    system_prompt: str = "Tu es CodeSensai.",
    run_turn: TurnRunner = run_agent_turn,
    allowed_origins: Sequence[str] = (),
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)  # pas de documentation publique
    sessions: dict[str, Session] = {}

    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),  # closed list, never "*"
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    def require_token(authorization: str | None = Header(default=None)) -> None:
        scheme, _, supplied = (authorization or "").partition(" ")
        ok = scheme.lower() == "bearer" and hmac.compare_digest(supplied.encode(), token.encode())
        if not ok:  # same answer for a missing, wrong or malformed token
            raise HTTPException(401, detail=error_body("UNAUTHORIZED", "Authentification requise"))

    def find(session_id: str) -> Session:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, detail=error_body("SESSION_NOT_FOUND", "Session introuvable"))
        return session

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}  # deliberately without authentication or detail

    @app.post("/api/sessions", status_code=201, dependencies=[Depends(require_token)])
    def create_session() -> dict[str, str]:
        session = Session(id=uuid.uuid4().hex[:12])
        sessions[session.id] = session
        return {"session_id": session.id}

    @app.get("/api/sessions/{session_id}", dependencies=[Depends(require_token)])
    def get_session(session_id: str) -> dict[str, Any]:
        session = find(session_id)
        return {"session_id": session.id, "messages": list(session.turns)}

    @app.post("/api/sessions/{session_id}/messages", dependencies=[Depends(require_token)])
    async def send_message(session_id: str, body: MessageIn) -> StreamingResponse:
        session = find(session_id)
        content = body.content.strip()
        if not content:
            raise HTTPException(400, detail=error_body("EMPTY_MESSAGE", "Message vide"))
        if len(content) > MAX_MESSAGE_CHARS:
            raise HTTPException(413, detail=error_body("MESSAGE_TOO_LONG", "Message trop long"))
        if session.busy:
            raise HTTPException(409, detail=error_body("TURN_IN_PROGRESS", "A turn is already in progress"))
        session.busy = True
        session.cancel.clear()

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def emit(item: dict | None) -> None:  # called from the agent thread
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:  # loop closed: the server is stopping, nobody is listening
                pass

        threading.Thread(
            target=run_turn_in_thread,
            args=(session, content, emit),
            kwargs={
                "run_turn": run_turn,
                "make_gateway": make_gateway,
                "host": host,
                "model": model,
                "system_prompt": system_prompt,
            },
            daemon=True,
        ).start()

        async def stream():
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"
            finally:
                # Normal end or browser disconnected: nothing more may be sent or run.
                session.cancel.set()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/sessions/{session_id}/confirm", status_code=204, dependencies=[Depends(require_token)])
    def confirm(session_id: str, body: ConfirmIn) -> Response:
        pending = find(session_id).pending.get(body.confirm_id)
        if pending is None:  # unknown, already resolved or expired: no effect
            raise HTTPException(404, detail=error_body("CONFIRM_NOT_FOUND", "Confirmation inconnue"))
        pending.approved = body.approved is True
        pending.event.set()
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/interrupt", status_code=204, dependencies=[Depends(require_token)])
    def interrupt(session_id: str) -> Response:
        session = find(session_id)
        if session.busy:
            session.cancel.set()
        return Response(status_code=204)

    return app
