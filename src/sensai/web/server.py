"""
[Workstream D] CodeSensai web server: the API of docs/architecture/web/web-api.md
on top of the real agent.

Decisions: ADR-0022 (one turn = one SSE stream, the agent in a thread),
ADR-0023 (token, local listening, closed CORS), ADR-0024 (contract extensions),
ADR-0035 (real server, same agent as the CLI).

- The core is synchronous: `WebRuntime.run_turn` runs in a thread and its
  events reach the asyncio loop through a queue.
- Confirmation goes through `WebConfirmationBroker` (Workstream B, ADR-0015),
  one per turn: only a timely "yes" authorizes; timeout, interruption or a
  closed tab refuse.
- Only one turn at a time per session (409), several sessions in parallel.
- Every API route requires the token, except `/api/health`.
- Errors follow the web-api.md format: `{"error", "code", "details"}`.
"""
from __future__ import annotations

import asyncio
import hmac
import html
import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool

from sensai.execution.guardrails import filter_output
from sensai.execution.web_confirmation import WebConfirmationBroker
from sensai.knowledge.facts import FactError
from sensai.knowledge.memory import ensure_private_dir
from sensai.knowledge.persona import Persona, PersonaError
from sensai.knowledge.rag import EmbeddingError
from sensai.scheduling.tasks import ScheduleStoreError, Task, parse_interval, validate_task_id
from sensai.web.questions import WebQuestionBroker
from sensai.web.runtime import WebRuntime

log = logging.getLogger("sensai.web")

MAX_MESSAGE_CHARS = 20_000
# Every preference goes into the system prompt on every turn: a cap prevents
# a client from filling the model's context.
MAX_PREFERENCES = 50


class ApiError(Exception):
    def __init__(self, status: int, code: str, error: str, details: str = "") -> None:
        super().__init__(error)
        self.status, self.code, self.error, self.details = status, code, error, details


@dataclass
class Live:
    """What exists only during a turn: the server keeps nothing else in memory."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    busy: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    broker: WebConfirmationBroker | None = None
    questions: WebQuestionBroker | None = None


class MessageIn(BaseModel):
    content: str
    # /again: ask the model again, bypassing the cache (A6).
    skip_cache: StrictBool = False


class ConfirmIn(BaseModel):
    confirm_id: str
    # Only the JSON boolean true authorizes (ADR-0015): not "true", 1 or "yes".
    approved: StrictBool


class AnswerIn(BaseModel):
    question_id: str
    # Validated against the form by WebQuestionBroker (X4, ADR-0046).
    values: dict[str, Any]


class TaskIn(BaseModel):
    id: str = Field(max_length=64)
    prompt: str = Field(max_length=4000)
    every: str = Field(max_length=16)  # "30m", "2h", "1d": like sensai-schedule


class EnabledIn(BaseModel):
    enabled: StrictBool


class ForgetFactIn(BaseModel):
    entity: str = Field(min_length=1, max_length=200)


class PreferenceIn(BaseModel):
    text: str = Field(max_length=500)


class PersonaIn(BaseModel):
    persona: str = Field(min_length=1, max_length=64)


class PromptTrialIn(BaseModel):
    # None: go back to the registry's active version (ADR-0055).
    version: str | None = Field(default=None, max_length=16)


class ForkIn(BaseModel):
    at_message: int = Field(ge=0)


# The public page of a share link (X3, ADR-0048): no script, no external
# resource, no indexing, no referrer sent.
SHARE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                               "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
}
SHARE_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;"
    "line-height:1.5;color:#1d1d1f;background:#fafafa}"
    "@media(prefers-color-scheme:dark){body{color:#eee;background:#141414}"
    "section{background:#1f1f1f!important}}"
    "section{background:#fff;border-radius:12px;padding:.8rem 1rem;margin:.8rem 0}"
    "h2{font-size:.85rem;margin:0 0 .3rem;opacity:.7}"
    "p.note{font-size:.8rem;opacity:.7}pre{white-space:pre-wrap;margin:0;font:inherit}"
)


def share_page(entry: dict[str, Any] | None) -> str:
    """The shared conversation as static HTML; all text is escaped."""
    if entry is None:
        body = ("<h1>Link unavailable</h1><p>This share link does not exist, "
                "has been revoked or has expired.</p>")
    else:
        parts = [f"<h1>CodeSensai conversation</h1><p class=note>Read-only copy, "
                 f"secrets masked. Available until "
                 f"{html.escape(str(entry['expires_at'])[:16].replace('T', ' '))} (UTC).</p>"]
        for m in entry["messages"]:
            who = "You" if m["role"] == "user" else "CodeSensai"
            parts.append(f"<section><h2>{who}</h2><pre>{html.escape(m['content'])}</pre></section>")
        body = "".join(parts)
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta name=robots content='noindex,nofollow'>"
            f"<title>Shared conversation</title><style>{SHARE_STYLE}</style></head>"
            f"<body>{body}</body></html>")


def create_app(
    runtime: WebRuntime,
    *,
    token: str,
    allowed_origins: Sequence[str] = (),
    frontend_dir: Path | None = None,
    adversarial_runner: Callable[[], dict[str, Any]] | None = None,
) -> FastAPI:
    if not token:
        raise ValueError("a token is required (ADR-0023)")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)  # no public documentation
    live: dict[str, Live] = {}
    live_lock = threading.Lock()

    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),  # closed list, never "*"
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": exc.error, "code": exc.code, "details": exc.details},
                            status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return JSONResponse({"error": "Invalid request", "code": "INVALID_REQUEST",
                             "details": details}, status_code=400)

    def require_token(authorization: str | None = Header(default=None)) -> None:
        scheme, _, supplied = (authorization or "").partition(" ")
        ok = scheme.lower() == "bearer" and hmac.compare_digest(supplied.encode(), token.encode())
        if not ok:  # same response for a missing, wrong or malformed token
            raise ApiError(401, "UNAUTHORIZED", "Authentication required")

    def known(session_id: str) -> str:
        if not runtime.store.exists(session_id):
            raise ApiError(404, "SESSION_NOT_FOUND", "Session not found",
                           f"Session {session_id} does not exist or has been purged")
        return session_id

    def live_of(session_id: str) -> Live:
        with live_lock:
            return live.setdefault(session_id, Live())

    auth = [Depends(require_token)]

    # --- Health and configuration -----------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}  # deliberately without authentication or details

    @app.get("/api/config", dependencies=auth)
    def config() -> dict[str, Any]:
        # ADR-0023: no Ollama address, no token, no full path.
        return {
            "model": runtime.model,
            "project": Path(runtime.project).name,
            "rag": runtime.rag_on,
            "rerank": bool(runtime.settings.get("rag_rerank", True)),
            "cache": runtime.cache is not None,
            "notices": list(runtime.notices),
        }

    # --- Sessions ---------------------------------------------------------------------

    @app.post("/api/sessions", status_code=201, dependencies=auth)
    def create_session() -> dict[str, str]:
        return {"session_id": runtime.store.create(runtime.project)}

    @app.get("/api/sessions", dependencies=auth)
    def list_sessions() -> list[dict[str, Any]]:
        return [
            {"session_id": s.id, "title": s.title, "created_at": s.created_at,
             "updated_at": s.updated_at, "message_count": s.message_count}
            for s in runtime.store.list(runtime.project) if s.message_count
        ]

    @app.get("/api/sessions/{session_id}", dependencies=auth)
    def get_session(session_id: str) -> dict[str, Any]:
        return {"session_id": session_id, "messages": runtime.store.load(known(session_id))}

    @app.post("/api/sessions/{session_id}/fork", status_code=201, dependencies=auth)
    def fork(session_id: str, body: ForkIn) -> dict[str, str]:
        """Fork (X2, ADR-0024): a new session with the first `at_message`
        messages of this one."""
        turns = runtime.store.load(known(session_id))
        if body.at_message > len(turns):
            raise ApiError(400, "INVALID_REQUEST", "Invalid fork point",
                           f"the session has {len(turns)} messages")
        new_id = runtime.store.create(runtime.project)
        runtime.store.save(new_id, turns[:body.at_message])
        return {"session_id": new_id}

    @app.post("/api/sessions/{session_id}/delete", status_code=204, dependencies=auth)
    def delete_session(session_id: str) -> Response:
        """Deletes a conversation and its messages (chat sidebar)."""
        state = live_of(known(session_id))
        with state.lock:
            if state.busy:
                raise ApiError(409, "TURN_IN_PROGRESS", "A turn is in progress")
            runtime.store.delete(session_id)
            # The conversation's EV3 log goes with it (docs/legal/local-data.md).
            if runtime.journal is not None:
                try:
                    runtime.journal.delete_session(session_id)
                except (OSError, sqlite3.Error) as e:
                    log.warning("EV3 log of %s not deleted: %s", session_id, e)
        with live_lock:
            live.pop(session_id, None)
        runtime.forget_session(session_id)
        return Response(status_code=204)

    @app.get("/api/sessions/{session_id}/export", dependencies=auth)
    def export(session_id: str, format: Literal["json", "md"] = "json") -> Response:
        """Export with secrets filtered (X3, ADR-0024); PDF stays browser-side."""
        turns = [{"role": t.get("role", ""), "content": filter_output(str(t.get("content", "")))}
                 for t in runtime.store.load(known(session_id))]
        name = f"codesensei-{session_id}"
        if format == "json":
            return JSONResponse({"session_id": session_id, "messages": turns}, headers={
                "Content-Disposition": f'attachment; filename="{name}.json"'})
        lines = [f"# Conversation {session_id}", ""]
        for t in turns:
            who = "You" if t["role"] == "user" else "CodeSensai"
            lines += [f"## {who}", "", t["content"], ""]
        disposition = f'attachment; filename="{name}.md"'
        return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": disposition})

    # --- Sharing (X3, ADR-0048) ------------------------------------------------------

    @app.post("/api/sessions/{session_id}/share", status_code=201, dependencies=auth)
    def share(session_id: str) -> dict[str, str]:
        # ADR-0056: a public link is readable without a token for 7 days; disabled by
        # default, the user enables it with `share_links: true` in config.json.
        if not runtime.settings.get("share_links", False):
            raise ApiError(403, "SHARE_DISABLED", "Share links disabled",
                           "enable them with \"share_links\": true in config.json")
        turns = runtime.store.load(known(session_id))
        if not turns:
            raise ApiError(400, "EMPTY_SESSION", "Nothing to share",
                           "the conversation has no messages yet")
        created = runtime.shares.create(session_id, turns)
        return {"url": f"/share/{created['token']}", "token": created["token"],
                "expires_at": created["expires_at"]}

    @app.post("/api/shares/{token}/revoke", status_code=204, dependencies=auth)
    def revoke(token: str) -> Response:
        if not runtime.shares.revoke(token):
            raise ApiError(404, "SHARE_NOT_FOUND", "Unknown share link")
        return Response(status_code=204)

    @app.get("/share/{token}", include_in_schema=False)
    def shared(token: str) -> HTMLResponse:
        # No API token: that is the point of the link. Unknown, revoked or
        # expired: the same 404 page, without saying which.
        entry = runtime.shares.get(token)
        return HTMLResponse(share_page(entry), status_code=200 if entry else 404,
                            headers=SHARE_HEADERS)

    # --- A turn ----------------------------------------------------------------------

    @app.post("/api/sessions/{session_id}/messages", dependencies=auth)
    async def send_message(session_id: str, body: MessageIn) -> StreamingResponse:
        known(session_id)
        content = body.content.strip()
        if not content:
            raise ApiError(400, "EMPTY_MESSAGE", "Empty message")
        if len(content) > MAX_MESSAGE_CHARS:
            raise ApiError(413, "MESSAGE_TOO_LONG", "Message too long",
                           f"{MAX_MESSAGE_CHARS} characters at most")
        state = live_of(session_id)
        with state.lock:
            if state.busy:
                raise ApiError(409, "TURN_IN_PROGRESS", "A turn is already in progress")
            state.busy = True
            state.cancel = threading.Event()

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def emit(item: dict | None) -> None:  # called from the agent's thread
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:  # loop closed: the server is stopping, nobody is listening
                pass

        def emit_confirm(payload: dict[str, Any]) -> None:
            # The broker names the key `id`; the reply expects `confirm_id`
            # (web-api-alignment.md, gap 9): send both.
            emit({**payload, "confirm_id": payload.get("id")})

        state.broker = WebConfirmationBroker(emit_confirm)
        state.questions = WebQuestionBroker(emit)
        cancel, broker, questions = state.cancel, state.broker, state.questions

        def work() -> None:
            try:
                turns = runtime.store.load(session_id)
                new_turns = runtime.run_turn(turns, content, emit, cancel, broker.confirmer,
                                             skip_cache=body.skip_cache, asker=questions.ask,
                                             session_id=session_id)
                if new_turns is not None:
                    runtime.store.save(session_id, new_turns)
            except Exception:  # the session may have been deleted meanwhile: never leave a hanging stream
                log.exception("web turn failed")
                emit({"type": "error", "message": "Internal server error."})
                emit({"type": "done", "reason": "error"})
            finally:
                broker.close()
                questions.close()
                with state.lock:
                    state.busy = False
                emit(None)  # end of stream

        threading.Thread(target=work, name=f"sensai-turn-{session_id}", daemon=True).start()

        async def stream():
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"
            finally:
                # Normal end or browser disconnected: nothing else may run.
                cancel.set()
                broker.close()
                questions.close()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/sessions/{session_id}/confirm", status_code=204, dependencies=auth)
    def confirm(session_id: str, body: ConfirmIn) -> Response:
        broker = live_of(known(session_id)).broker
        if broker is None or not broker.resolve(body.confirm_id, body.approved):
            # Unknown, already resolved or expired: no effect.
            raise ApiError(404, "CONFIRM_NOT_FOUND", "Unknown or expired confirmation")
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/answer", status_code=204, dependencies=auth)
    def answer(session_id: str, body: AnswerIn) -> Response:
        """Answer to a question from the agent (X4, ADR-0046)."""
        questions = live_of(known(session_id)).questions
        outcome = "unknown" if questions is None else questions.resolve(body.question_id,
                                                                         body.values)
        if outcome == "unknown":
            raise ApiError(404, "QUESTION_NOT_FOUND", "Unknown or expired question")
        if outcome != "ok":
            raise ApiError(400, "INVALID_ANSWER", "Invalid answer", outcome)
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/interrupt", status_code=204, dependencies=auth)
    def interrupt(session_id: str) -> Response:
        state = live_of(known(session_id))
        if state.busy:
            state.cancel.set()
            if state.broker is not None:
                state.broker.close()  # a pending confirmation becomes a refusal
            if state.questions is not None:
                state.questions.close()  # a pending question stays unanswered
        return Response(status_code=204)

    # --- Personas, per conversation (A5, Workstream A; web: ADR-0054)---------------------

    def persona_view(p: Persona) -> dict[str, Any]:
        return {"id": p.id, "name": p.name, "role": p.role, "tone": p.tone, "scope": p.scope,
                "tools_disabled": sorted(p.tools_disabled),
                "default": p.id == runtime.personas.default_id}

    def idle(session_id: str) -> Live:
        """The session exists and no turn is running in it: otherwise 404 / 409."""
        state = live_of(known(session_id))
        if state.busy:
            raise ApiError(409, "TURN_IN_PROGRESS", "A turn is in progress",
                           "wait for the turn to end before changing this setting")
        return state

    @app.get("/api/personas", dependencies=auth)
    def list_personas() -> list[dict[str, Any]]:
        return [persona_view(runtime.personas.get(i)) for i in runtime.personas.names()]

    @app.get("/api/sessions/{session_id}/persona", dependencies=auth)
    def get_persona(session_id: str) -> dict[str, Any]:
        return persona_view(runtime.persona_of(known(session_id)))

    @app.post("/api/sessions/{session_id}/persona", dependencies=auth)
    def set_persona(session_id: str, body: PersonaIn) -> dict[str, Any]:
        state = idle(session_id)
        with state.lock:
            if state.busy:
                raise ApiError(409, "TURN_IN_PROGRESS", "A turn is in progress")
            try:
                persona = runtime.set_persona(session_id, body.persona)
            except PersonaError as e:
                raise ApiError(404, "PERSONA_NOT_FOUND", "Unknown persona", str(e)) from e
        return persona_view(persona)

    # --- Prompt versions, read-only (A4, Workstream A; web: ADR-0055) ----------------
    # The registry is never written here: making a version active for everyone remains
    # `sensai-prompt use`. The web only trials a version within one conversation.

    def prompt_name(name: str) -> str:
        if name not in runtime.prompt_store.names():
            raise ApiError(404, "PROMPT_NOT_FOUND", "Unknown prompt", name)
        return name

    def prompt_version(name: str, version: str) -> str:
        try:
            return runtime.prompt_store.resolve(prompt_name(name), version)
        except KeyError as e:
            raise ApiError(404, "PROMPT_VERSION_NOT_FOUND", "Unknown version",
                           f"{name} {version}") from e

    @app.get("/api/prompts", dependencies=auth)
    def list_prompts() -> list[dict[str, Any]]:
        store = runtime.prompt_store
        return [{"name": n, "active": store.active(n), "versions": store.history(n)}
                for n in store.names()]

    @app.get("/api/prompts/{name}/diff", dependencies=auth)
    def prompt_diff(name: str, a: str, b: str) -> dict[str, str]:
        old, new = prompt_version(name, a), prompt_version(name, b)
        return {"name": name, "a": old, "b": new,
                "diff": runtime.prompt_store.diff(name, old, new)}

    @app.get("/api/prompts/{name}/{version}", dependencies=auth)
    def prompt_text(name: str, version: str) -> dict[str, str]:
        version_id = prompt_version(name, version)
        return {"name": name, "version": version_id,
                "text": runtime.prompt_store.load(name, version_id)}

    def trial_view(session_id: str) -> dict[str, Any]:
        store = runtime.prompt_store
        active = store.active("system") if "system" in store.names() else None
        return {"prompt": "system", "active": active,
                "trial": runtime.prompt_trial_of(session_id)}

    @app.get("/api/sessions/{session_id}/prompt-trial", dependencies=auth)
    def get_prompt_trial(session_id: str) -> dict[str, Any]:
        return trial_view(known(session_id))

    @app.post("/api/sessions/{session_id}/prompt-trial", dependencies=auth)
    def set_prompt_trial(session_id: str, body: PromptTrialIn) -> dict[str, Any]:
        state = idle(session_id)
        with state.lock:
            if state.busy:
                raise ApiError(409, "TURN_IN_PROGRESS", "A turn is in progress")
            if body.version is not None:
                prompt_version("system", body.version)
            runtime.set_prompt_trial(session_id, body.version)
        return trial_view(session_id)

    # --- Memories, read-only ----------------------------------------------------------

    @app.get("/api/profile", dependencies=auth)
    def profile() -> dict[str, Any]:
        p = runtime.profile
        return {"name": p.name, "instructions": p.instructions, "preferences": list(p.preferences)}

    @app.post("/api/profile/preferences", dependencies=auth)
    def add_preference(body: PreferenceIn) -> dict[str, Any]:
        """US-WEB-6: adds a preference (empty or already present: ignored), like
        `/remember` in the CLI. The profile is reread on every turn (system prompt)."""
        text = body.text.strip()
        with runtime._profile_lock:
            p = runtime.profile
            if text and text not in p.preferences:
                if len(p.preferences) >= MAX_PREFERENCES:
                    raise ApiError(400, "TOO_MANY_PREFERENCES", "Too many preferences",
                                   f"{MAX_PREFERENCES} at most")
                p.remember(text)
                p.save(runtime.profile_path)
        return profile()

    @app.post("/api/profile/forget", dependencies=auth)
    def forget_preferences() -> dict[str, Any]:
        """US-WEB-6: clears all preferences, like `/forget` in the CLI. POST rather
        than DELETE /api/profile: the server only allows GET and POST (CORS)."""
        with runtime._profile_lock:
            runtime.profile.forget()
            runtime.profile.save(runtime.profile_path)
        return profile()

    @app.post("/api/facts/forget", dependencies=auth)
    def forget_fact(body: ForgetFactIn) -> dict[str, Any]:
        """Forgets an entity's facts (like `/facts forget` in the CLI). Trial run of
        2026-11-01: deleting a conversation does not delete the facts saved during
        it, so they had to be forgettable from the web."""
        try:
            removed = runtime.facts.forget(body.entity)
        except FactError as e:
            raise ApiError(400, "INVALID_REQUEST", "Cannot forget", str(e)) from e
        if not removed:
            raise ApiError(404, "FACT_NOT_FOUND", "No facts for this entity")
        return {"removed": removed}

    @app.get("/api/fewshot", dependencies=auth)
    def fewshot() -> dict[str, Any]:
        """The configured few-shot examples (A7, ADR-0044), read-only."""
        return runtime.fewshot_info()

    @app.get("/api/facts", dependencies=auth)
    def facts() -> dict[str, Any]:
        try:
            entities = runtime.facts.entities(limit=200)
            return {"facts": {e: runtime.facts.recall(entity=e) for e in entities}}
        except FactError as e:
            raise ApiError(500, "FACTS_UNAVAILABLE", "Fact memory unreadable", str(e)) from e

    @app.get("/api/state", dependencies=auth)
    def state_document() -> dict[str, Any]:
        # `bodies`: the content of each section, for the Artifact panel (M4).
        return {"markdown": runtime.state.read() or "", "sections": runtime.state.sections(),
                "bodies": runtime.state.bodies()}

    # --- On-demand evaluation (EV1) -------------------------------------------------

    @app.post("/api/sessions/{session_id}/evaluate", dependencies=auth)
    def evaluate(session_id: str) -> dict[str, Any]:
        """Has the judge score the conversation's last answer (one model call)."""
        turns = runtime.store.load(known(session_id))
        try:
            result = runtime.evaluate(turns)
        except ValueError as e:
            raise ApiError(400, "NOTHING_TO_EVALUATE", "Nothing to evaluate", str(e)) from e
        except (EmbeddingError, OSError) as e:
            raise ApiError(502, "EVALUATION_FAILED", "Evaluation failed", str(e)) from e
        if result.get("status") != "ok":
            raise ApiError(502, "EVALUATION_FAILED", "The judge returned no usable score",
                           str(result.get("error", "")))
        return {"scores": result["scores"], "passages": result["passages"],
                "question": result["question"],
                "flagged": [{"text": filter_output(str(c.get("text", ""))),
                             "verdict": c.get("verdict")} for c in result.get("flagged", [])]}

    # --- Adversarial corpus (EV4, Workstream B) ---------------------------------------

    adversarial = {"last": None}
    adversarial_lock = threading.Lock()

    def run_adversarial() -> dict[str, Any]:
        # Late import: the corpus imports a lot (cli, gateway, sandbox) and is only
        # used here. No model; the containers are test doubles (docker_fakes).
        from sensai.eval.adversarial import results_to_json, run_corpus
        ran_at = datetime.now(UTC).isoformat(timespec="seconds")
        return results_to_json(run_corpus(), ran_at, "run")

    runner = adversarial_runner or run_adversarial

    @app.get("/api/quality/adversarial", dependencies=auth)
    def adversarial_results() -> dict[str, Any]:
        """This server's last run, otherwise the table committed in the repository."""
        if adversarial["last"] is not None:
            return adversarial["last"]
        from sensai.eval.adversarial import committed_results
        return committed_results()

    @app.post("/api/quality/adversarial/run", dependencies=auth)
    def adversarial_run() -> dict[str, Any]:
        """Replays the 85 attacks (a few seconds). Synchronous route: FastAPI runs it
        in a worker thread, the server loop stays free."""
        if not adversarial_lock.acquire(blocking=False):
            raise ApiError(409, "ALREADY_RUNNING", "The attacks are already running")
        try:
            result = runner()
        except Exception as e:  # a broken case must not leak a raw traceback to the client
            log.exception("EV4 corpus failed")
            raise ApiError(500, "ADVERSARIAL_FAILED", "The corpus could not run",
                           type(e).__name__) from e
        finally:
            adversarial_lock.release()
        adversarial["last"] = result
        return result

    # --- Turn log (EV3, Workstream D) -------------------------------------

    def journal_or_503():
        if runtime.journal is None:
            raise ApiError(503, "JOURNAL_UNAVAILABLE", "Log unavailable",
                           "journal.db could not be opened (see the server logs)")
        return runtime.journal

    @app.get("/api/journal", dependencies=auth)
    def journal(session: str, limit: int = 50) -> dict[str, Any]:
        """A conversation's turns, most recent first, with their tools."""
        try:
            turns = journal_or_503().turns(session, max(1, min(limit, 500)))
        except sqlite3.Error as e:
            raise ApiError(500, "JOURNAL_UNREADABLE", "Log unreadable", str(e)) from e
        return {"session_id": session, "turns": turns}

    @app.get("/api/journal/metrics", dependencies=auth)
    def journal_metrics(days: int = 7) -> dict[str, Any]:
        """Per tool and for the model, across all conversations and interfaces."""
        try:
            return journal_or_503().metrics(max(1, min(days, 3650)))
        except sqlite3.Error as e:
            raise ApiError(500, "JOURNAL_UNREADABLE", "Log unreadable", str(e)) from e

    # --- Scheduled tasks (X5) --------------------------------------------------------

    def task_view(task: Task) -> dict[str, Any]:
        due = task.next_due()
        return {**task.to_dict(), "next_due": due.isoformat() if due else None}

    @app.get("/api/schedule/tasks", dependencies=auth)
    def list_tasks() -> list[dict[str, Any]]:
        try:
            return [task_view(t) for t in runtime.tasks.load()]
        except (ValueError, ScheduleStoreError) as e:
            raise ApiError(500, "TASKS_UNREADABLE", "Task file unreadable", str(e)) from e

    @app.post("/api/schedule/tasks", status_code=201, dependencies=auth)
    def add_task(body: TaskIn) -> dict[str, Any]:
        """Like `sensai-schedule add`: the task is run by `sensai-schedule loop`
        (or `run-due`), not by the web server."""
        try:
            task_id = validate_task_id(body.id)
            interval = parse_interval(body.every)
            if not body.prompt.strip():
                raise ValueError("The prompt is empty.")
            ensure_private_dir(runtime.tasks.path.parent.parent)
            ensure_private_dir(runtime.tasks.path.parent)
            task = Task(id=task_id, prompt=body.prompt.strip(), interval_s=interval)
            runtime.tasks.add(task)
        except ScheduleStoreError as e:
            raise ApiError(500, "TASKS_UNREADABLE", "Task file unreadable", str(e)) from e
        except ValueError as e:
            raise ApiError(400, "INVALID_TASK", "Task rejected", str(e)) from e
        return task_view(task)

    @app.post("/api/schedule/tasks/{task_id}/remove", status_code=204, dependencies=auth)
    def remove_task(task_id: str) -> Response:
        if not runtime.tasks.remove(task_id):
            raise ApiError(404, "TASK_NOT_FOUND", "Unknown task")
        return Response(status_code=204)

    @app.post("/api/schedule/tasks/{task_id}/enabled", status_code=204, dependencies=auth)
    def enable_task(task_id: str, body: EnabledIn) -> Response:
        if not runtime.tasks.update(task_id, enabled=body.enabled):
            raise ApiError(404, "TASK_NOT_FOUND", "Unknown task")
        return Response(status_code=204)

    # --- The built frontend -------------------------------------------------------------

    if frontend_dir is not None and (frontend_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app
