"""
[Lot D] Serveur web de CodeSensei : l'API de docs/architecture/web/web-api.md
au-dessus du vrai agent.

Décisions : ADR-0022 (un tour = un flux SSE, l'agent dans un thread),
ADR-0023 (jeton, écoute locale, CORS fermé), ADR-0024 (extensions du contrat),
ADR-0035 (serveur réel, même agent que le CLI).

- Le cœur est synchrone : `WebRuntime.run_turn` tourne dans un thread et ses
  événements passent à la boucle asyncio par une file.
- La confirmation passe par `WebConfirmationBroker` (lot B, ADR-0015), un par
  tour : seul « oui » à temps autorise ; délai, interruption ou onglet fermé
  refusent.
- Un seul tour à la fois par session (409), plusieurs sessions en parallèle.
- Toute route de l'API demande le jeton, sauf `/api/health`.
- Les erreurs suivent le format de web-api.md : `{"error", "code", "details"}`.
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
# Chaque préférence entre dans le prompt système à chaque tour : une borne évite
# qu'un client remplisse le contexte du modèle.
MAX_PREFERENCES = 50


class ApiError(Exception):
    def __init__(self, status: int, code: str, error: str, details: str = "") -> None:
        super().__init__(error)
        self.status, self.code, self.error, self.details = status, code, error, details


@dataclass
class Live:
    """Ce qui n'existe que pendant un tour : le serveur ne garde rien d'autre en mémoire."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    busy: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    broker: WebConfirmationBroker | None = None
    questions: WebQuestionBroker | None = None


class MessageIn(BaseModel):
    content: str
    # /again : redemander au modèle sans passer par le cache (A6).
    skip_cache: StrictBool = False


class ConfirmIn(BaseModel):
    confirm_id: str
    # Seul le booléen JSON true autorise (ADR-0015) : pas "true", 1 ni "yes".
    approved: StrictBool


class AnswerIn(BaseModel):
    question_id: str
    # Validées contre le formulaire par WebQuestionBroker (X4, ADR-0046).
    values: dict[str, Any]


class TaskIn(BaseModel):
    id: str = Field(max_length=64)
    prompt: str = Field(max_length=4000)
    every: str = Field(max_length=16)  # « 30m », « 2h », « 1d » : comme sensai-schedule


class EnabledIn(BaseModel):
    enabled: StrictBool


class ForgetFactIn(BaseModel):
    entity: str = Field(min_length=1, max_length=200)


class PreferenceIn(BaseModel):
    text: str = Field(max_length=500)


class PersonaIn(BaseModel):
    persona: str = Field(min_length=1, max_length=64)


class PromptTrialIn(BaseModel):
    # None : revenir à la version active du registre (ADR-0055).
    version: str | None = Field(default=None, max_length=16)


class ForkIn(BaseModel):
    at_message: int = Field(ge=0)


# La page publique d'un lien de partage (X3, ADR-0048) : aucun script, aucune
# ressource externe, pas d'indexation, pas de référent transmis.
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
    """La conversation partagée en HTML statique ; tout le texte est échappé."""
    if entry is None:
        body = ("<h1>Lien indisponible</h1><p>Ce lien de partage n'existe pas, "
                "a été révoqué ou a expiré.</p>")
    else:
        parts = [f"<h1>Conversation CodeSensei</h1><p class=note>Copie en lecture seule, "
                 f"secrets masqués. Disponible jusqu'au "
                 f"{html.escape(str(entry['expires_at'])[:16].replace('T', ' '))} (UTC).</p>"]
        for m in entry["messages"]:
            who = "Vous" if m["role"] == "user" else "CodeSensei"
            parts.append(f"<section><h2>{who}</h2><pre>{html.escape(m['content'])}</pre></section>")
        body = "".join(parts)
    return (f"<!doctype html><html lang=fr><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta name=robots content='noindex,nofollow'>"
            f"<title>Conversation partagée</title><style>{SHARE_STYLE}</style></head>"
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
        raise ValueError("un jeton est obligatoire (ADR-0023)")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)  # pas de documentation publique
    live: dict[str, Live] = {}
    live_lock = threading.Lock()

    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),  # liste fermée, jamais « * »
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": exc.error, "code": exc.code, "details": exc.details},
                            status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = "; ".join(f"{'.'.join(map(str, e['loc']))} : {e['msg']}" for e in exc.errors())
        return JSONResponse({"error": "Requête invalide", "code": "INVALID_REQUEST",
                             "details": details}, status_code=400)

    def require_token(authorization: str | None = Header(default=None)) -> None:
        scheme, _, supplied = (authorization or "").partition(" ")
        ok = scheme.lower() == "bearer" and hmac.compare_digest(supplied.encode(), token.encode())
        if not ok:  # même réponse pour jeton absent, faux ou mal formé
            raise ApiError(401, "UNAUTHORIZED", "Authentification requise")

    def known(session_id: str) -> str:
        if not runtime.store.exists(session_id):
            raise ApiError(404, "SESSION_NOT_FOUND", "Session introuvable",
                           f"La session {session_id} n'existe pas ou a été purgée")
        return session_id

    def live_of(session_id: str) -> Live:
        with live_lock:
            return live.setdefault(session_id, Live())

    auth = [Depends(require_token)]

    # --- Santé et configuration ---------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}  # volontairement sans authentification et sans détail

    @app.get("/api/config", dependencies=auth)
    def config() -> dict[str, Any]:
        # ADR-0023 : ni adresse Ollama, ni jeton, ni chemin complet.
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
        """Bifurcation (X2, ADR-0024) : une nouvelle session, avec les `at_message`
        premiers messages de celle-ci."""
        turns = runtime.store.load(known(session_id))
        if body.at_message > len(turns):
            raise ApiError(400, "INVALID_REQUEST", "Point de bifurcation invalide",
                           f"la session a {len(turns)} messages")
        new_id = runtime.store.create(runtime.project)
        runtime.store.save(new_id, turns[:body.at_message])
        return {"session_id": new_id}

    @app.post("/api/sessions/{session_id}/delete", status_code=204, dependencies=auth)
    def delete_session(session_id: str) -> Response:
        """Supprime une conversation et ses messages (barre latérale du chat)."""
        state = live_of(known(session_id))
        with state.lock:
            if state.busy:
                raise ApiError(409, "TURN_IN_PROGRESS", "Un tour est en cours")
            runtime.store.delete(session_id)
            # Le journal EV3 de la conversation part avec elle (docs/legal/donnees-locales.md).
            if runtime.journal is not None:
                try:
                    runtime.journal.delete_session(session_id)
                except (OSError, sqlite3.Error) as e:
                    log.warning("journal EV3 de %s non supprimé : %s", session_id, e)
        with live_lock:
            live.pop(session_id, None)
        runtime.forget_session(session_id)
        return Response(status_code=204)

    @app.get("/api/sessions/{session_id}/export", dependencies=auth)
    def export(session_id: str, format: Literal["json", "md"] = "json") -> Response:
        """Export filtré des secrets (X3, ADR-0024) ; le PDF reste côté navigateur."""
        turns = [{"role": t.get("role", ""), "content": filter_output(str(t.get("content", "")))}
                 for t in runtime.store.load(known(session_id))]
        name = f"codesensei-{session_id}"
        if format == "json":
            return JSONResponse({"session_id": session_id, "messages": turns}, headers={
                "Content-Disposition": f'attachment; filename="{name}.json"'})
        lines = [f"# Conversation {session_id}", ""]
        for t in turns:
            who = "Vous" if t["role"] == "user" else "CodeSensei"
            lines += [f"## {who}", "", t["content"], ""]
        disposition = f'attachment; filename="{name}.md"'
        return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": disposition})

    # --- Partage (X3, ADR-0048) ------------------------------------------------------

    @app.post("/api/sessions/{session_id}/share", status_code=201, dependencies=auth)
    def share(session_id: str) -> dict[str, str]:
        # ADR-0056 : un lien public se lit sans jeton pendant 7 jours ; désactivé par
        # défaut, Marc l'active avec `share_links: true` dans config.json.
        if not runtime.settings.get("share_links", False):
            raise ApiError(403, "SHARE_DISABLED", "Liens de partage désactivés",
                           "les activer avec \"share_links\": true dans config.json")
        turns = runtime.store.load(known(session_id))
        if not turns:
            raise ApiError(400, "EMPTY_SESSION", "Rien à partager",
                           "la conversation n'a encore aucun message")
        created = runtime.shares.create(session_id, turns)
        return {"url": f"/share/{created['token']}", "token": created["token"],
                "expires_at": created["expires_at"]}

    @app.post("/api/shares/{token}/revoke", status_code=204, dependencies=auth)
    def revoke(token: str) -> Response:
        if not runtime.shares.revoke(token):
            raise ApiError(404, "SHARE_NOT_FOUND", "Lien de partage inconnu")
        return Response(status_code=204)

    @app.get("/share/{token}", include_in_schema=False)
    def shared(token: str) -> HTMLResponse:
        # Sans jeton d'API : c'est le principe du lien. Inconnu, révoqué ou
        # expiré : la même page 404, sans dire lequel.
        entry = runtime.shares.get(token)
        return HTMLResponse(share_page(entry), status_code=200 if entry else 404,
                            headers=SHARE_HEADERS)

    # --- Un tour ----------------------------------------------------------------------

    @app.post("/api/sessions/{session_id}/messages", dependencies=auth)
    async def send_message(session_id: str, body: MessageIn) -> StreamingResponse:
        known(session_id)
        content = body.content.strip()
        if not content:
            raise ApiError(400, "EMPTY_MESSAGE", "Message vide")
        if len(content) > MAX_MESSAGE_CHARS:
            raise ApiError(413, "MESSAGE_TOO_LONG", "Message trop long",
                           f"{MAX_MESSAGE_CHARS} caractères au plus")
        state = live_of(session_id)
        with state.lock:
            if state.busy:
                raise ApiError(409, "TURN_IN_PROGRESS", "Un tour est déjà en cours")
            state.busy = True
            state.cancel = threading.Event()

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def emit(item: dict | None) -> None:  # appelé depuis le thread de l'agent
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:  # boucle fermée : le serveur s'arrête, plus personne n'écoute
                pass

        def emit_confirm(payload: dict[str, Any]) -> None:
            # Le broker nomme la clé `id` ; la réponse attend `confirm_id`
            # (web-api-alignement.md, écart 9) : on envoie les deux.
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
            except Exception:  # la session a pu être supprimée entre-temps : jamais de flux pendu
                log.exception("tour web en échec")
                emit({"type": "error", "message": "Erreur interne du serveur."})
                emit({"type": "done", "reason": "error"})
            finally:
                broker.close()
                questions.close()
                with state.lock:
                    state.busy = False
                emit(None)  # fin du flux

        threading.Thread(target=work, name=f"sensai-turn-{session_id}", daemon=True).start()

        async def stream():
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"
            finally:
                # Fin normale ou navigateur déconnecté : plus rien ne doit s'exécuter.
                cancel.set()
                broker.close()
                questions.close()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/sessions/{session_id}/confirm", status_code=204, dependencies=auth)
    def confirm(session_id: str, body: ConfirmIn) -> Response:
        broker = live_of(known(session_id)).broker
        if broker is None or not broker.resolve(body.confirm_id, body.approved):
            # Inconnue, déjà résolue ou expirée : sans effet.
            raise ApiError(404, "CONFIRM_NOT_FOUND", "Confirmation inconnue ou expirée")
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/answer", status_code=204, dependencies=auth)
    def answer(session_id: str, body: AnswerIn) -> Response:
        """Réponse à une question de l'agent (X4, ADR-0046)."""
        questions = live_of(known(session_id)).questions
        outcome = "unknown" if questions is None else questions.resolve(body.question_id,
                                                                         body.values)
        if outcome == "unknown":
            raise ApiError(404, "QUESTION_NOT_FOUND", "Question inconnue ou expirée")
        if outcome != "ok":
            raise ApiError(400, "INVALID_ANSWER", "Réponse invalide", outcome)
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/interrupt", status_code=204, dependencies=auth)
    def interrupt(session_id: str) -> Response:
        state = live_of(known(session_id))
        if state.busy:
            state.cancel.set()
            if state.broker is not None:
                state.broker.close()  # une confirmation en attente devient un refus
            if state.questions is not None:
                state.questions.close()  # une question en attente reste sans réponse
        return Response(status_code=204)

    # --- Personas, par conversation (A5, lot A ; web : ADR-0054) ------------------------

    def persona_view(p: Persona) -> dict[str, Any]:
        return {"id": p.id, "name": p.name, "role": p.role, "tone": p.tone, "scope": p.scope,
                "tools_disabled": sorted(p.tools_disabled),
                "default": p.id == runtime.personas.default_id}

    def idle(session_id: str) -> Live:
        """La session existe et aucun tour n'y tourne : sinon 404 / 409."""
        state = live_of(known(session_id))
        if state.busy:
            raise ApiError(409, "TURN_IN_PROGRESS", "Un tour est en cours",
                           "attendre la fin du tour pour changer ce réglage")
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
                raise ApiError(409, "TURN_IN_PROGRESS", "Un tour est en cours")
            try:
                persona = runtime.set_persona(session_id, body.persona)
            except PersonaError as e:
                raise ApiError(404, "PERSONA_NOT_FOUND", "Persona inconnue", str(e)) from e
        return persona_view(persona)

    # --- Versions de prompts, en lecture (A4, lot A ; web : ADR-0055) -----------------
    # Le registre n'est jamais écrit ici : rendre une version active pour tous reste
    # `sensai-prompt use`. Le web ne fait qu'essayer une version dans une conversation.

    def prompt_name(name: str) -> str:
        if name not in runtime.prompt_store.names():
            raise ApiError(404, "PROMPT_NOT_FOUND", "Prompt inconnu", name)
        return name

    def prompt_version(name: str, version: str) -> str:
        try:
            return runtime.prompt_store.resolve(prompt_name(name), version)
        except KeyError as e:
            raise ApiError(404, "PROMPT_VERSION_NOT_FOUND", "Version inconnue",
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
                raise ApiError(409, "TURN_IN_PROGRESS", "Un tour est en cours")
            if body.version is not None:
                prompt_version("system", body.version)
            runtime.set_prompt_trial(session_id, body.version)
        return trial_view(session_id)

    # --- Mémoires, en lecture ---------------------------------------------------------

    @app.get("/api/profile", dependencies=auth)
    def profile() -> dict[str, Any]:
        p = runtime.profile
        return {"name": p.name, "instructions": p.instructions, "preferences": list(p.preferences)}

    @app.post("/api/profile/preferences", dependencies=auth)
    def add_preference(body: PreferenceIn) -> dict[str, Any]:
        """US-WEB-6 : ajoute une préférence (vide ou déjà présente : ignorée), comme
        `/remember` dans le CLI. Le profil est relu à chaque tour (prompt système)."""
        text = body.text.strip()
        with runtime._profile_lock:
            p = runtime.profile
            if text and text not in p.preferences:
                if len(p.preferences) >= MAX_PREFERENCES:
                    raise ApiError(400, "TOO_MANY_PREFERENCES", "Trop de préférences",
                                   f"{MAX_PREFERENCES} au plus")
                p.remember(text)
                p.save(runtime.profile_path)
        return profile()

    @app.post("/api/profile/forget", dependencies=auth)
    def forget_preferences() -> dict[str, Any]:
        """US-WEB-6 : efface toutes les préférences, comme `/forget` dans le CLI. En POST
        plutôt qu'en DELETE /api/profile : le serveur n'ouvre que GET et POST (CORS)."""
        with runtime._profile_lock:
            runtime.profile.forget()
            runtime.profile.save(runtime.profile_path)
        return profile()

    @app.post("/api/facts/forget", dependencies=auth)
    def forget_fact(body: ForgetFactIn) -> dict[str, Any]:
        """Oublie les faits d'une entité (comme `/facts forget` dans le CLI). Essai du
        2026-11-01 : supprimer une conversation ne supprime pas les faits retenus pendant
        celle-ci, il fallait pouvoir les oublier depuis le web."""
        try:
            removed = runtime.facts.forget(body.entity)
        except FactError as e:
            raise ApiError(400, "INVALID_REQUEST", "Oubli impossible", str(e)) from e
        if not removed:
            raise ApiError(404, "FACT_NOT_FOUND", "Aucun fait pour cette entité")
        return {"removed": removed}

    @app.get("/api/fewshot", dependencies=auth)
    def fewshot() -> dict[str, Any]:
        """Les exemples few-shot configurés (A7, ADR-0044), en lecture seule."""
        return runtime.fewshot_info()

    @app.get("/api/facts", dependencies=auth)
    def facts() -> dict[str, Any]:
        try:
            entities = runtime.facts.entities(limit=200)
            return {"facts": {e: runtime.facts.recall(entity=e) for e in entities}}
        except FactError as e:
            raise ApiError(500, "FACTS_UNAVAILABLE", "Mémoire de faits illisible", str(e)) from e

    @app.get("/api/state", dependencies=auth)
    def state_document() -> dict[str, Any]:
        # `bodies` : le contenu de chaque section, pour le panneau Artefact (M4).
        return {"markdown": runtime.state.read() or "", "sections": runtime.state.sections(),
                "bodies": runtime.state.bodies()}

    # --- Évaluation à la demande (EV1) ------------------------------------------------

    @app.post("/api/sessions/{session_id}/evaluate", dependencies=auth)
    def evaluate(session_id: str) -> dict[str, Any]:
        """Fait juger la dernière réponse de la conversation (un appel au modèle)."""
        turns = runtime.store.load(known(session_id))
        try:
            result = runtime.evaluate(turns)
        except ValueError as e:
            raise ApiError(400, "NOTHING_TO_EVALUATE", "Rien à évaluer", str(e)) from e
        except (EmbeddingError, OSError) as e:
            raise ApiError(502, "EVALUATION_FAILED", "Évaluation impossible", str(e)) from e
        if result.get("status") != "ok":
            raise ApiError(502, "EVALUATION_FAILED", "Le juge n'a pas rendu de note exploitable",
                           str(result.get("error", "")))
        return {"scores": result["scores"], "passages": result["passages"],
                "question": result["question"],
                "flagged": [{"text": filter_output(str(c.get("text", ""))),
                             "verdict": c.get("verdict")} for c in result.get("flagged", [])]}

    # --- Corpus adversarial (EV4, lot B — Méric) ---------------------------------------

    adversarial = {"last": None}
    adversarial_lock = threading.Lock()

    def run_adversarial() -> dict[str, Any]:
        # Import tardif : le corpus importe beaucoup (cli, passerelle, sandbox) et ne
        # sert qu'ici. Aucun modèle ; les conteneurs sont des doubles (docker_fakes).
        from sensai.eval.adversarial import results_to_json, run_corpus
        ran_at = datetime.now(UTC).isoformat(timespec="seconds")
        return results_to_json(run_corpus(), ran_at, "run")

    runner = adversarial_runner or run_adversarial

    @app.get("/api/quality/adversarial", dependencies=auth)
    def adversarial_results() -> dict[str, Any]:
        """Le dernier passage de ce serveur, sinon le tableau versionné du dépôt."""
        if adversarial["last"] is not None:
            return adversarial["last"]
        from sensai.eval.adversarial import committed_results
        return committed_results()

    @app.post("/api/quality/adversarial/run", dependencies=auth)
    def adversarial_run() -> dict[str, Any]:
        """Rejoue les 85 attaques (quelques secondes). Route synchrone : FastAPI la fait
        tourner dans un thread de travail, la boucle du serveur reste libre."""
        if not adversarial_lock.acquire(blocking=False):
            raise ApiError(409, "ALREADY_RUNNING", "Les attaques sont déjà en cours")
        try:
            result = runner()
        except Exception as e:  # un cas cassé ne doit pas laisser une trace brute au client
            log.exception("corpus EV4 en échec")
            raise ApiError(500, "ADVERSARIAL_FAILED", "Le corpus n'a pas pu tourner",
                           type(e).__name__) from e
        finally:
            adversarial_lock.release()
        adversarial["last"] = result
        return result

    # --- Journal des tours (EV3, lot D — Valentino) -------------------------------------

    def journal_or_503():
        if runtime.journal is None:
            raise ApiError(503, "JOURNAL_UNAVAILABLE", "Journal indisponible",
                           "journal.db n'a pas pu être ouvert (voir les logs du serveur)")
        return runtime.journal

    @app.get("/api/journal", dependencies=auth)
    def journal(session: str, limit: int = 50) -> dict[str, Any]:
        """Les tours d'une conversation, le plus récent d'abord, avec leurs outils."""
        try:
            turns = journal_or_503().turns(session, max(1, min(limit, 500)))
        except sqlite3.Error as e:
            raise ApiError(500, "JOURNAL_UNREADABLE", "Journal illisible", str(e)) from e
        return {"session_id": session, "turns": turns}

    @app.get("/api/journal/metrics", dependencies=auth)
    def journal_metrics(days: int = 7) -> dict[str, Any]:
        """Par outil et pour le modèle, toutes conversations et interfaces confondues."""
        try:
            return journal_or_503().metrics(max(1, min(days, 3650)))
        except sqlite3.Error as e:
            raise ApiError(500, "JOURNAL_UNREADABLE", "Journal illisible", str(e)) from e

    # --- Tâches planifiées (X5) -------------------------------------------------------

    def task_view(task: Task) -> dict[str, Any]:
        due = task.next_due()
        return {**task.to_dict(), "next_due": due.isoformat() if due else None}

    @app.get("/api/schedule/tasks", dependencies=auth)
    def list_tasks() -> list[dict[str, Any]]:
        try:
            return [task_view(t) for t in runtime.tasks.load()]
        except (ValueError, ScheduleStoreError) as e:
            raise ApiError(500, "TASKS_UNREADABLE", "Fichier des tâches illisible", str(e)) from e

    @app.post("/api/schedule/tasks", status_code=201, dependencies=auth)
    def add_task(body: TaskIn) -> dict[str, Any]:
        """Comme `sensai-schedule add` : la tâche est exécutée par `sensai-schedule loop`
        (ou `run-due`), pas par le serveur web."""
        try:
            task_id = validate_task_id(body.id)
            interval = parse_interval(body.every)
            if not body.prompt.strip():
                raise ValueError("Le prompt est vide.")
            ensure_private_dir(runtime.tasks.path.parent.parent)
            ensure_private_dir(runtime.tasks.path.parent)
            task = Task(id=task_id, prompt=body.prompt.strip(), interval_s=interval)
            runtime.tasks.add(task)
        except ScheduleStoreError as e:
            raise ApiError(500, "TASKS_UNREADABLE", "Fichier des tâches illisible", str(e)) from e
        except ValueError as e:
            raise ApiError(400, "INVALID_TASK", "Tâche refusée", str(e)) from e
        return task_view(task)

    @app.post("/api/schedule/tasks/{task_id}/remove", status_code=204, dependencies=auth)
    def remove_task(task_id: str) -> Response:
        if not runtime.tasks.remove(task_id):
            raise ApiError(404, "TASK_NOT_FOUND", "Tâche inconnue")
        return Response(status_code=204)

    @app.post("/api/schedule/tasks/{task_id}/enabled", status_code=204, dependencies=auth)
    def enable_task(task_id: str, body: EnabledIn) -> Response:
        if not runtime.tasks.update(task_id, enabled=body.enabled):
            raise ApiError(404, "TASK_NOT_FOUND", "Tâche inconnue")
        return Response(status_code=204)

    # --- L'interface construite ---------------------------------------------------------

    if frontend_dir is not None and (frontend_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app
