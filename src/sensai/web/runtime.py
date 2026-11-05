"""
[Lot D] L'agent du serveur web : les mêmes pièces que le CLI (ADR-0035).

Un `WebRuntime` par serveur, pour le projet d'où `sensai-web` est lancé. Il
assemble ce que `cli.main` assemble : registre partagé, recherche dans le
projet (R1, R2), document d'état (M4), mémoire de faits (M3), passerelle avec
garde-fous (EV2), filtre d'entrée, cache sémantique (A6) et sessions (M1).
Le CLI n'est pas modifié ; `tests/web/test_runtime.py` vérifie que les deux
proposent les mêmes outils.

`run_turn` joue un tour et publie des dictionnaires prêts pour le flux SSE :
le flux du lot A (`to_wire`) et les extensions de l'ADR-0024 que le serveur
produit seul (`rag_sources`, `cache_hit`, `guardrail`,
`done.reason = "interrupted"`). Il tourne dans un thread de travail : la
confirmation web bloque ce thread (ADR-0015, ADR-0022).
"""
from __future__ import annotations

import atexit
import functools
import hashlib
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from sensai.config import prompts_dir, resolve_path
from sensai.core.agent import run_agent_turn
from sensai.core.answer import AnswerBuilder
from sensai.core.context_view import COMMAND as CONTEXT_COMMAND
from sensai.core.context_view import describe_context
from sensai.core.events import Done, Event, Token, ToolCall, ToolReturn, to_wire
from sensai.core.ollama_client import generation_options
from sensai.eval.judge import find_judge_store, judge_case, load_judge_prompt, ollama_judge
from sensai.eval.sources import rag_sources
from sensai.execution.gateway import ConfirmationRequest, ToolGateway
from sensai.execution.guardrails import InputRules, check_input, filter_input, filter_output
from sensai.execution.sandbox.document_sandbox import DocumentSandbox
from sensai.knowledge.cache import CACHE_FILE, AnswerCache, handle_cache_command
from sensai.knowledge.compression import (
    DEFAULT_KEEP_RECENT,
    DEFAULT_NUM_CTX,
    CompressionError,
    compress_messages,
    count_message_tokens,
    exceeds_budget,
    resolve_budget,
)
from sensai.knowledge.facts import FACTS_FILE, FactStore, handle_facts_command
from sensai.knowledge.fewshot import (
    FewShotError,
    FewShotIndex,
    format_example,
    worth_attaching,
)
from sensai.knowledge.memory import (
    PROFILE_FILE,
    SESSIONS_FILE,
    Profile,
    SessionStore,
    build_system_prompt,
    default_data_dir,
    handle_command,
    local_datetime,
)
from sensai.knowledge.persona import Persona, PersonaStore
from sensai.knowledge.prompt_versions import PromptStore
from sensai.knowledge.rag import RAG_FILE, EmbeddingError, OllamaEmbedder, RagIndex, format_context
from sensai.knowledge.retrieval import LlmReranker
from sensai.knowledge.state_document import STATE_FILE, StateDocument, handle_state_command
from sensai.observability.journal import TurnRecorder, open_journal
from sensai.registry import build_registry
from sensai.scheduling.tasks import TASKS_FILE, TaskStore
from sensai.tools.ask_user_tool import Asker, AskUserTool
from sensai.tools.delegate_tool import DelegateTool
from sensai.tools.fact_tools import RecallFactsTool, RememberFactTool
from sensai.tools.mcp_tool import load_mcp_tools
from sensai.tools.project_tests import project_test_runner
from sensai.tools.rag_tool import RagTool
from sensai.tools.schedule_task_tool import ScheduleTaskTool
from sensai.tools.state_tool import UpdateStateTool
from sensai.tools.team_tool import TeamTool
from sensai.web.shares import SHARES_FILE, ShareStore

log = logging.getLogger(__name__)

Emit = Callable[[dict[str, Any]], None]
Confirmer = Callable[[ConfirmationRequest], bool]
TurnRunner = Callable[[str, str, list[dict], Any], Iterator[Event]]

# Comme le CLI (A6, ADR-0033) : seule une réponse appuyée sur ces outils de
# lecture du projet peut être mise en cache.
CACHEABLE_TOOLS = {"read_file", "search_codebase"}
_PASSAGE_SOURCE = re.compile(r"^--- (.+?):\d+-\d+$", re.MULTILINE)
# Résultats de web_search (« 1. titre » puis l'URL, voir web_search_tool._format) :
# l'onglet Sources de l'interface les liste (US-T3-1). Liens http(s) seulement.
_WEB_RESULT = re.compile(r"^\d+\. (.+)\n {3}(https?://\S+)$", re.MULTILINE)
# /schedule et /eval affichent dans le terminal (ADR-0028) : pas dans le web.
TERMINAL_ONLY = ("/schedule", "/eval")
# L'agent principal dans les événements `agent_handoff` (X1, A2) ; l'interface
# le remplace par le nom de la persona affichée.
MAIN_AGENT = "main"
DELEGATION_TOOLS = {"delegate_task", "team_task"}
# Ce qu'on montre d'un résultat d'outil d'un sous-agent : un aperçu, pas tout le fichier lu.
SUBAGENT_STEP_CHARS = 600


class Handoffs:
    """Suit l'agent qui a la main pendant un tour et publie chaque passage de relais.

    Annoncé quand le sous-agent démarre vraiment (après la confirmation), jamais
    sur la seule demande du modèle : une délégation refusée n'affiche aucun relais.
    Délégation simple : un aller (vers le rôle, ou « sous-agent ») et un retour.
    Équipe : un relais par rôle (explorateur → développeur → relecteur…), puis le
    retour à l'agent principal à la fin de l'outil.
    """

    def __init__(self, emit: Emit, recorder: TurnRecorder | None = None) -> None:
        self.emit = emit
        self.current = MAIN_AGENT
        # Journal EV3 : chaque outil d'un sous-agent y est noté avec sa durée.
        self.recorder = recorder

    def to(self, agent: str) -> None:
        if agent != self.current:
            self.emit({"type": "agent_handoff", "from": self.current, "to": agent})
            self.current = agent

    def on_return(self, event: ToolReturn) -> None:
        if event.name in DELEGATION_TOOLS:
            self.to(MAIN_AGENT)

    def step(self, tool: str, arguments: dict, ok: bool, content: str,
             duration_ms: int | None = None) -> None:
        """Un outil exécuté par le sous-agent qui a la main (A2) : l'interface le montre
        dans le raisonnement du tour. Le contenu est déjà filtré par la passerelle (EV2).
        `duration_ms` : mesurée côté serveur autour de l'appel (EV3)."""
        event = {"type": "subagent_step", "agent": self.current, "tool": tool,
                 "arguments": arguments, "ok": ok, "content": content[:SUBAGENT_STEP_CHARS]}
        if duration_ms is not None:
            event["duration_ms"] = duration_ms
        self.emit(event)
        if self.recorder is not None:
            self.recorder.subagent_call(tool, arguments, ok, duration_ms or 0, self.current)


class _Timed:
    """Enveloppe la passerelle vue par les sous-agents pour chronométrer chaque appel
    (EV3) ; le sous-agent appelle les outils dans le thread du tour, un à la fois."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.last_ms = 0

    def describe_all(self) -> list[dict[str, Any]]:
        return self.inner.describe_all()

    def call(self, name: str, /, **kwargs: Any) -> Any:
        started = time.monotonic()
        try:
            return self.inner.call(name, **kwargs)
        finally:
            self.last_ms = round((time.monotonic() - started) * 1000)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.inner, attr)


def _relative(path: str, project: str) -> str:
    try:
        return str(Path(project, path).resolve().relative_to(project))
    except ValueError:
        return path


class _AnnouncedDelegate(DelegateTool):
    """`delegate_task` qui annonce le relais au moment où le sous-agent démarre."""

    def __init__(self, *args: Any, handoffs: Handoffs | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.handoffs = handoffs
        self.tools = _Timed(self.tools)

    def run(self, **kwargs: Any):
        if self.handoffs is not None and str(kwargs.get("task") or "").strip():
            self.handoffs.to(str(kwargs.get("role") or "sous-agent"))
        return super().run(**kwargs)

    def delegate(self, task: str, *, on_call=None, **kwargs: Any):
        """Chaque outil du sous-agent est aussi publié (A2), y compris pour l'équipe
        (`team_task` appelle cette méthode pour chaque rôle)."""
        handoffs = self.handoffs
        if handoffs is None:
            return super().delegate(task, on_call=on_call, **kwargs)

        def seen(name: str, args: dict, result: Any) -> None:
            handoffs.step(name, args, bool(result.ok), str(result.content),
                          duration_ms=self.tools.last_ms)
            if on_call is not None:
                on_call(name, args, result)

        return super().delegate(task, on_call=seen, **kwargs)


class WebRuntime:
    """L'agent et ses mémoires pour un projet, partagés par toutes les sessions web."""

    def __init__(
        self,
        settings: dict,
        project: str | Path,
        *,
        run_turn: TurnRunner | None = None,
        embedder_factory: Callable[[str, str], Any] = OllamaEmbedder,
        converter_factory: Callable[[], Any] = DocumentSandbox,
        reranker_factory: Callable[..., Any] | None = LlmReranker,
        judge_factory: Callable[..., Any] = ollama_judge,
        prompt_store: PromptStore | None = None,
    ) -> None:
        self.settings = settings
        self.project = str(Path(project).resolve())
        self.model = settings["model"]
        self.host = settings["host"]
        # M2 (ADR-0045) : comme le CLI, la fenêtre de contexte part avec chaque appel
        # au modèle ; sans elle, Ollama tronque en silence à sa valeur par défaut.
        self.num_ctx = settings.get("num_ctx")
        self._run_turn = run_turn or functools.partial(
            run_agent_turn, num_ctx=self.num_ctx, max_iterations=settings.get("max_iterations"))
        self._embedder_factory = embedder_factory
        self._converter_factory = converter_factory
        self._reranker_factory = reranker_factory
        self._judge_factory = judge_factory

        data_dir = settings.get("data_dir")
        self.data_dir = Path(data_dir).expanduser() if data_dir else default_data_dir()
        self.store = SessionStore(self.data_dir / SESSIONS_FILE)
        # Liens de partage (X3, ADR-0048), à côté des sessions.
        self.shares = ShareStore(self.data_dir / SHARES_FILE)
        # Tâches planifiées (X5) : le même fichier que `sensai-schedule`, qui les exécute.
        self.tasks = TaskStore(self.data_dir / "schedule" / TASKS_FILE)
        # Journal des tours (EV3, ADR-0053) : None s'il ne s'ouvre pas, le chat continue.
        self.journal = open_journal(self.data_dir)
        self.profile_path = self.data_dir / PROFILE_FILE
        try:
            self.profile = Profile.load(self.profile_path)
        except ValueError as e:
            log.warning("profil illisible, démarrage avec un profil vide : %s", e)
            self.profile = Profile()
        # Une règle mal écrite arrête le démarrage (comme le CLI, ADR-0027).
        self.input_rules = InputRules.from_config(settings.get("input_blocklist"))
        key = hashlib.sha256(self.project.encode("utf-8")).hexdigest()[:16]
        self.state = StateDocument(self.project, self.data_dir / "state" / f"{key}.jsonl")
        self.facts = FactStore(self.data_dir / FACTS_FILE, self.project)
        self.rag_tool = RagTool(min_score=settings["rag_min_score"])
        self.rag_on = bool(settings["rag"])
        self.rag_index: RagIndex | None = None
        self.notices: list[str] = []  # avertissements à montrer dans l'interface
        # Serveurs MCP (T1, ADR-0041) : lancés une fois pour tout le serveur web,
        # leurs outils ajoutés à chaque passerelle ; une panne devient un avertissement.
        self.mcp_tools, mcp_warnings, self.close_mcp = load_mcp_tools(
            settings.get("mcp_servers") or {})
        atexit.register(self.close_mcp)
        self.notices += mcp_warnings
        self._rag_lock = threading.Lock()
        self._profile_lock = threading.Lock()
        self.cache = self._open_cache()
        self._fewshot: FewShotIndex | None = None
        self._fewshot_off = False
        # Personas (A5, ADR-0042/0043 ; web : ADR-0054). Comme le CLI : la persona
        # active n'est qu'une étiquette en mémoire, ici une par conversation ; rien
        # n'est enregistré, une conversation rouverte repart de la persona par défaut.
        self.personas: PersonaStore = settings.get("personas") or PersonaStore.from_config(None)
        # Registre des prompts (A4, ADR-0010 ; web : ADR-0055) : lu, jamais écrit par
        # le serveur. Un essai de version ne vaut que pour une conversation, en mémoire.
        self.prompt_store = prompt_store or PromptStore(prompts_dir())
        self._session_persona: dict[str, str] = {}
        self._session_prompt_trial: dict[str, str] = {}
        # Heure du premier tour de chaque conversation : figée dans le prompt système,
        # sinon il changerait à chaque tour et Ollama relirait toute la conversation.
        self._session_started: dict[str, datetime] = {}
        self._session_lock = threading.Lock()

    # --- Démarrage ---------------------------------------------------------------

    def _open_cache(self) -> AnswerCache | None:
        if not self.settings.get("cache", False):
            return None
        try:
            return AnswerCache(self.data_dir / CACHE_FILE, self.project,
                               self._embedder_factory(self.host, self.settings["rag_model"]),
                               model=self.model)
        except (sqlite3.Error, OSError) as e:
            self.notices.append(f"Cache des réponses désactivé : {e}")
            return None

    def purge(self) -> int:
        """Sessions et journal d'état trop anciens (M1, M4) ; issue #65."""
        days = self.settings["retention_days"]
        try:
            self.state.purge(days)
        except (OSError, ValueError) as e:
            log.warning("purge du journal d'état impossible : %s", e)
        if self.journal is not None:
            try:
                self.journal.purge(days)
            except (OSError, ValueError, sqlite3.Error) as e:
                log.warning("purge du journal EV3 impossible : %s", e)
        try:
            self.shares.purge()
        except (OSError, ValueError) as e:
            log.warning("purge des liens de partage impossible : %s", e)
        try:
            return self.store.purge(days)
        except sqlite3.Error as e:
            log.warning("purge des sessions impossible : %s", e)
            return 0

    def ensure_index(self) -> RagIndex | None:
        """Ouvre et met à jour l'index du projet à la première question, puis le tient
        à jour au fil des questions (comme le CLI)."""
        if not self.rag_on:
            return None
        with self._rag_lock:
            if self.rag_index is not None:
                # Les fichiers créés ou modifiés depuis (souvent par l'agent) entrent
                # dans la recherche ; au plus une mise à jour toutes les 30 s.
                try:
                    self.rag_index.refresh_if_stale(Path(self.project))
                except (EmbeddingError, sqlite3.Error, OSError) as e:
                    self._notice(f"Index du projet pas mis à jour : {e}")
                return self.rag_index
            rag_model = self.settings["rag_model"]
            try:
                index = RagIndex(self.data_dir / RAG_FILE, self.project,
                                 self._embedder_factory(self.host, rag_model), model=rag_model,
                                 converter=self._converter_factory())
                if self.settings.get("rag_rerank", True) and self._reranker_factory:
                    index.reranker = self._reranker_factory(
                        self.host, self.model, num_ctx=self.num_ctx)
                report = index.update(Path(self.project))
            except (EmbeddingError, sqlite3.Error, OSError) as e:
                self.rag_on = False
                self.notices.append(f"Recherche dans le projet désactivée : {e}")
                return None
            for path, advice in report.unsupported:
                self.notices.append(f"Non indexé : {_relative(str(path), self.project)} — {advice}")
            self.rag_index = index
            self.rag_tool.index = index
            return index

    # --- Persona et essai de prompt, par conversation (ADR-0054, ADR-0055) -------

    def persona_of(self, session_id: str | None) -> Persona:
        with self._session_lock:
            persona_id = self._session_persona.get(session_id or "", self.personas.default_id)
        return self.personas.get(persona_id)

    def set_persona(self, session_id: str, persona_id: str) -> Persona:
        """PersonaError si la persona est inconnue (le serveur en fait un 404)."""
        persona = self.personas.get(persona_id)
        with self._session_lock:
            self._session_persona[session_id] = persona.id
        return persona

    def prompt_trial_of(self, session_id: str | None) -> str | None:
        with self._session_lock:
            return self._session_prompt_trial.get(session_id or "")

    def set_prompt_trial(self, session_id: str, version: str | None) -> str | None:
        """Essaie une version du prompt système dans cette conversation (None : revient
        à la version active). KeyError si la version n'existe pas. Le registre n'est
        que lu : `PromptStore.use` reste réservé à `sensai-prompt use`."""
        with self._session_lock:
            if version is None:
                self._session_prompt_trial.pop(session_id, None)
                return None
        version_id = self.prompt_store.resolve("system", version)
        with self._session_lock:
            self._session_prompt_trial[session_id] = version_id
        return version_id

    def started_at(self, session_id: str | None) -> datetime:
        """L'heure du premier tour de la conversation, retenue en mémoire du serveur."""
        with self._session_lock:
            key = session_id or ""
            if key not in self._session_started:
                self._session_started[key] = local_datetime()
            return self._session_started[key]

    def forget_session(self, session_id: str) -> None:
        with self._session_lock:
            self._session_started.pop(session_id, None)
            self._session_persona.pop(session_id, None)
            self._session_prompt_trial.pop(session_id, None)

    # --- Agent -------------------------------------------------------------------

    def system_prompt(self, resumed: bool, persona: Persona | None = None,
                      prompt_version: str | None = None,
                      started: datetime | None = None) -> str:
        """Comme le CLI : prompt, consigne de reprise, profil, persona, SENSAI.md, faits.

        `prompt_version` : une version du registre essayée dans cette conversation
        (ADR-0055) à la place du prompt système chargé au démarrage.
        """
        try:
            known = self.facts.as_prompt()
        except (OSError, sqlite3.Error) as e:
            log.warning("mémoire de faits illisible : %s", e)
            known = ""
        note = self.settings.get("memory_prompt", "") if resumed else ""
        base_prompt = self.settings.get("system_prompt", "")
        if prompt_version is not None:
            base_prompt = self.prompt_store.load("system", prompt_version).strip()
        persona = persona or self.personas.default()
        with self._profile_lock:
            return build_system_prompt(base_prompt, self.profile, note, now=started,
                                       extra=(persona.as_prompt(), self.state.as_prompt(), known))

    def make_gateway(self, confirmer: Confirmer, asker: Asker | None = None,
                     handoffs: Handoffs | None = None, persona: Persona | None = None,
                     prompt_version: str | None = None,
                     started: datetime | None = None) -> ToolGateway:
        registry = build_registry(self.settings.get("file_permissions"))
        # X4 (ADR-0046) : sans navigateur pour répondre (`asker` absent), l'outil
        # existe quand même et répond « personne ne peut répondre ».
        registry.register(AskUserTool(asker))
        # Planifier en langage naturel (X5, ADR-0052) : toujours sur accord explicite.
        registry.register(ScheduleTaskTool(self.data_dir))
        for tool in self.mcp_tools:
            registry.register(tool)
        if self.rag_on:
            registry.register(self.rag_tool)
        registry.register(UpdateStateTool(self.state))
        registry.register(RememberFactTool(self.facts))
        registry.register(RecallFactsTool(self.facts))
        gateway = ToolGateway(registry, self.settings.get("tool_preferences"), confirm=confirmer,
                              input_guards=[check_input], output_filters=[filter_output])
        # Comme le CLI (A5, ADR-0043) : une persona ne peut qu'AJOUTER des outils
        # désactivés à ceux de config.json, jamais en réautoriser un.
        persona = persona or self.personas.default()
        if persona.tools_disabled:
            base = gateway.preferences
            gateway.preferences = replace(base, disabled=base.disabled | persona.tools_disabled)
        # Comme le CLI (A2, ADR-0037) : le sous-agent passe par cette même passerelle
        # (donc les mêmes outils refusés) et reçoit le même prompt (persona comprise).
        delegate = _AnnouncedDelegate(self.host, self.model, gateway,
                                      system_prompt=lambda: self.system_prompt(
                                          resumed=False, persona=persona,
                                          prompt_version=prompt_version, started=started),
                                      num_ctx=self.num_ctx, handoffs=handoffs)
        registry.register(delegate)
        registry.register(TeamTool(delegate, on_handoff=handoffs.to if handoffs else None,
                                   test_runner=project_test_runner(self.project)))
        return gateway

    def command(self, text: str) -> str | None:
        """Les commandes du chat (`/state`, `/facts`, `/cache`, `/remember`…), comme le CLI."""
        if text.split()[0] in TERMINAL_ONLY:
            return "Cette commande s'utilise dans le terminal (sensai)."
        for handler in (lambda t: handle_state_command(t, self.state),
                        lambda t: handle_facts_command(t, self.facts),
                        lambda t: handle_cache_command(t, self.cache)):
            output = handler(text)
            if output is not None:
                return output
        with self._profile_lock:
            return handle_command(text, self.profile, self.profile_path, self.store, self.project)

    def run_turn(
        self,
        turns: list[dict],
        text: str,
        emit: Emit,
        cancel: threading.Event,
        confirmer: Confirmer,
        *,
        skip_cache: bool = False,
        asker: Asker | None = None,
        session_id: str | None = None,
    ) -> list[dict] | None:
        """Joue un tour et renvoie l'historique à enregistrer, ou None s'il ne change pas.

        Toujours terminé par un `done`. Un tour interrompu, en échec, bloqué ou
        une commande n'entre pas dans l'historique (comme le CLI).
        """
        try:
            return self._turn(turns, text, emit, cancel, confirmer, skip_cache, asker,
                              session_id)
        except Exception:  # un bug ne doit ni laisser le flux ouvert ni fuiter une trace
            log.exception("tour d'agent en échec")
            emit({"type": "error", "message": "Erreur interne du serveur."})
            emit({"type": "done", "reason": "error"})
            return None

    def _within_budget(self, messages: list[dict], emit: Emit | None = None) -> list[dict]:
        """Budget de tokens et résumé glissant (M2, ADR-0045), comme le CLI.

        Appelé APRÈS avoir ajouté le RAG à la question, et seule la copie envoyée
        au modèle est compactée : les tours enregistrés dans la session (M1) ne
        sont jamais touchés. Un échec du résumé, ou un contexte trop gros pour
        être réduit, devient un avertissement de l'interface, jamais une perte
        d'historique.
        """
        max_tokens = self.settings.get("token_budget_max")
        if not self.settings.get("token_budget", True):
            self._emit_usage(messages, max_tokens, emit)
            return messages
        try:
            compacted, compressed = compress_messages(
                self.host, self.model, messages, max_tokens=max_tokens,
                keep_recent=self.settings.get("token_budget_keep_recent", DEFAULT_KEEP_RECENT),
                num_ctx=self.num_ctx)
        except CompressionError as e:
            self._notice(f"Résumé automatique de l'historique impossible pour ce tour : {e}")
            self._emit_usage(messages, max_tokens, emit)
            return messages
        if not compressed and exceeds_budget(messages, max_tokens, self.num_ctx):
            self._notice("Le contexte d'un tour dépasse le budget de tokens et ne peut pas être "
                         "résumé : Ollama risque de le tronquer.")
        if compressed and emit is not None:
            saved = count_message_tokens(messages) - count_message_tokens(compacted)
            emit({"type": "compression", "saved_tokens": max(saved, 0)})
        self._emit_usage(compacted, max_tokens, emit)
        return compacted

    def _emit_usage(self, messages: list[dict], max_tokens: int | None, emit: Emit | None) -> None:
        """M2 : ce qui part au modèle à ce tour, en tokens ESTIMÉS (caractères / 4,
        ADR-0045), face au budget et à la fenêtre `num_ctx`."""
        if emit is None:
            return
        used = count_message_tokens(messages)
        window = self.num_ctx or DEFAULT_NUM_CTX
        emit({"type": "usage", "used": used, "budget": resolve_budget(max_tokens, self.num_ctx),
              "num_ctx": window, "estimated": True})

    def evaluate(self, turns: list[dict]) -> dict[str, Any]:
        """EV1 à la demande : fait juger la dernière réponse (pertinence, cohérence,
        fidélité aux passages du projet), avec le juge de `sensai-eval`.

        Un appel au modèle de plus : c'est pour ça que ce n'est pas fait à chaque
        tour. Sans recherche dans le projet, la fidélité n'a pas de passages et vaut
        None. Lève ValueError s'il n'y a pas de réponse à juger.
        """
        pairs = [(turns[i]["content"], turns[i + 1]["content"]) for i in range(len(turns) - 1)
                 if turns[i].get("role") == "user" and turns[i + 1].get("role") == "assistant"]
        if not pairs:
            raise ValueError("aucune réponse à évaluer dans cette conversation")
        question, answer = pairs[-1]
        passages = []
        index = self.ensure_index()
        if index is not None:
            passages = rag_sources(index, self.settings["rag_top_k"],
                                   self.settings["rag_min_score"])(question)
        prompt = load_judge_prompt(find_judge_store())
        result = judge_case(question, answer, passages,
                            self._judge_factory(self.host, self.model, num_ctx=self.num_ctx),
                            prompt.text)
        result["passages"] = len(passages)
        result["question"] = question[:200]
        return result

    def _state_bodies(self) -> dict[str, str]:
        try:
            return self.state.bodies()
        except (OSError, UnicodeDecodeError) as e:
            log.warning("document d'état illisible : %s", e)
            return {}

    def ensure_fewshot(self) -> FewShotIndex | None:
        """Exemples few-shot (A7), chargés à la première question ; None si non configurés."""
        configured = self.settings.get("fewshot_examples")
        if not configured or self._fewshot_off:
            return None
        with self._rag_lock:
            if self._fewshot is not None:
                return self._fewshot
            path = resolve_path(configured)
            if path is None:
                self._fewshot_failed(f"fichier introuvable : {configured}")
                return None
            index = FewShotIndex(self._embedder_factory(self.host, self.settings["rag_model"]),
                                 self.settings.get("fewshot_min_score", 0.75))
            try:
                index.load(path)
            except (FewShotError, EmbeddingError, OSError) as e:
                self._fewshot_failed(e)
                return None
            self._fewshot = index
            return index

    def fewshot_info(self) -> dict[str, Any]:
        """Ce que l'interface montre de l'A7 : fichier, seuil, questions des exemples.
        Charge les exemples s'ils ne l'ont pas encore été (même chemin qu'un tour)."""
        configured = self.settings.get("fewshot_examples")
        info: dict[str, Any] = {"configured": bool(configured), "file": configured or None,
                                "min_score": self.settings.get("fewshot_min_score", 0.75),
                                "questions": [], "error": None}
        if not configured:
            return info
        index = self.ensure_fewshot()
        if index is None:
            info["error"] = next((n for n in reversed(self.notices) if "few-shot" in n),
                                 "exemples few-shot désactivés")
            return info
        info["questions"] = index.questions()
        return info

    def _fewshot_failed(self, reason: object) -> None:
        self._fewshot_off = True
        self._fewshot = None
        self._notice(f"Exemples few-shot désactivés : {reason}")

    def _notice(self, text: str) -> None:
        """Un avertissement de l'interface, une seule fois même si le cas se répète."""
        if text not in self.notices:
            self.notices.append(text)

    def _turn(self, turns, text, emit, cancel, confirmer, skip_cache, asker=None,
              session_id=None):
        allowed, text = filter_input(text, self.input_rules)
        if not allowed:
            emit({"type": "guardrail", "kind": "unsafe", "message": text})
            emit({"type": "done", "reason": "blocked"})
            return None

        if text.strip() == CONTEXT_COMMAND:
            # Ce qui partirait au modèle dans cette conversation (ADR-0058) : même
            # prompt système que le tour (persona, essai de prompt, heure), même historique.
            system = self.system_prompt(
                resumed=bool(turns), persona=self.persona_of(session_id),
                prompt_version=self.prompt_trial_of(session_id),
                started=self.started_at(session_id))
            emit({"type": "token", "text": describe_context(
                [{"role": "system", "content": system}, *turns], self.num_ctx,
                self.settings.get("token_budget_max"), generation_options())})
            emit({"type": "done", "reason": "command"})
            return None

        if text.startswith("/"):
            try:
                output = self.command(text)
            except (OSError, sqlite3.Error) as e:
                output = f"Commande impossible : {e}"
            if output is not None:
                emit({"type": "token", "text": output})
                emit({"type": "done", "reason": "command"})
                return None

        # Fixées pour tout le tour : le serveur refuse de les changer pendant un tour (409).
        persona = self.persona_of(session_id)
        prompt_version = self.prompt_trial_of(session_id)
        # Comme le CLI (ADR-0043) : une persona qui restreint les outils ne lit ni
        # n'alimente le cache ; un essai de prompt non plus (ADR-0055) — une réponse
        # rangée sous une autre version du prompt ne dit rien de celle qu'on essaie.
        cache_usable = (self.cache is not None and not persona.tools_disabled
                        and prompt_version is None)

        if cache_usable and not skip_cache:
            try:
                hit = self.cache.lookup(text)
            except (EmbeddingError, sqlite3.Error, OSError, ValueError) as e:
                self.notices.append(f"Cache des réponses désactivé : {e}")
                self.cache = None
                hit = None
            if hit is not None:
                emit({"type": "cache_hit", "similarity": hit.similarity, "question": hit.question,
                      "created_at": hit.created_at.isoformat()})
                emit({"type": "token", "text": hit.answer})
                emit({"type": "done", "reason": "final_answer"})
                return [*turns, {"role": "user", "content": text},
                        {"role": "assistant", "content": hit.answer}]

        context, sources = None, []
        index = self.ensure_index()
        if index is not None:
            try:
                hits = index.search(text, top_k=self.settings["rag_top_k"],
                                    min_score=self.settings["rag_min_score"])
            except (EmbeddingError, sqlite3.Error, OSError) as e:
                self.rag_on = False
                self.notices.append(f"Recherche dans le projet désactivée : {e}")
                hits = None
            if hits is not None:
                # Mêmes garde-fous que les sorties d'outils (EV2) : sans eux, une clé
                # lue dans le projet partait en clair au modèle (essai du 2026-10-24).
                context = filter_output(format_context(hits))
                sources = [h["source"] for h in hits]
                emit({"type": "rag_sources", "sources": [
                    {"path": h["source"], "lines": f"{h['start']}-{h['end']}", "score": h["score"]}
                    for h in hits]})

        # Few-shot automatique (A7, ADR-0044), comme le CLI : rien si aucun exemple
        # n'est assez proche ; filtré par les garde-fous EV2 comme le RAG.
        fewshot_block = None
        fewshot = self.ensure_fewshot()
        if fewshot is not None:
            try:
                example = fewshot.best_match(text)
            except EmbeddingError as e:
                self._fewshot_failed(e)
                example = None
            if example is not None and not worth_attaching(example, text,
                                                           self.profile.preferences):
                example = None
            if example is not None:
                fewshot_block = filter_output(format_example(example, self.profile.preferences))
                emit({"type": "fewshot", "question": str(getattr(example, "question", ""))[:200]})

        prelude = "\n\n".join(p for p in (fewshot_block, context) if p)
        content = f"{prelude}\n\nQuestion : {text}" if prelude else text
        session_start = self.started_at(session_id)
        messages = [{"role": "system", "content": self.system_prompt(
                        resumed=bool(turns), persona=persona, prompt_version=prompt_version,
                        started=session_start)},
                    *turns, {"role": "user", "content": content}]
        messages = self._within_budget(messages, emit)
        state_before = self._state_bodies()

        answer = AnswerBuilder()
        reason = "error"
        cacheable = True
        started = time.monotonic()
        # Journal EV3 : chronomètre lancé juste avant le modèle (RAG et résumé exclus).
        recorder = TurnRecorder(self.journal, session_id=session_id, project=self.project,
                                interface="web", tokens_sent=count_message_tokens(messages))
        handoffs = Handoffs(emit, recorder)
        gateway = self.make_gateway(confirmer, asker, handoffs, persona=persona,
                                    prompt_version=prompt_version, started=session_start)
        generator = self._run_turn(self.host, self.model, messages, gateway)
        try:
            for event in generator:
                if cancel.is_set():
                    recorder.finish("interrupted")
                    emit({"type": "done", "reason": "interrupted"})
                    return None
                recorder.on_event(event)
                # Le retour à l'agent principal passe avant le `tool_return` qui le
                # provoque : l'interface montre le relais, puis le résultat.
                if isinstance(event, ToolReturn):
                    handoffs.on_return(event)
                if isinstance(event, Token):
                    answer.add(event.text)
                elif isinstance(event, ToolCall):
                    answer.tool_boundary()
                    if event.name not in CACHEABLE_TOOLS:
                        cacheable = False
                    elif event.name == "read_file" and event.arguments.get("path"):
                        sources.append(_relative(str(event.arguments["path"]), self.project))
                elif isinstance(event, ToolReturn) and event.name == "search_codebase":
                    sources += _PASSAGE_SOURCE.findall(event.content)
                elif isinstance(event, Done):
                    reason = event.reason
                emit(to_wire(event))
                if isinstance(event, ToolReturn) and event.name == "web_search" and event.ok:
                    found = _WEB_RESULT.findall(event.content)
                    if found:
                        emit({"type": "web_results",
                              "results": [{"title": t, "url": u} for t, u in found]})
                # M4 : une section du document d'état modifiée par l'agent est
                # envoyée à l'interface (panneau Artefact), seulement si elle a changé.
                if isinstance(event, ToolReturn) and event.name == "update_state" and event.ok:
                    state_after = self._state_bodies()
                    for name, body in state_after.items():
                        if state_before.get(name) != body:
                            emit({"type": "artifact_patch", "section": name, "markdown": body})
                    state_before = state_after
        finally:
            generator.close()
            recorder.finish("interrupted" if cancel.is_set() else None)
        if cancel.is_set() or reason != "final_answer":
            return None

        reply = answer.text()
        if cache_usable and self.cache is not None and cacheable:
            try:
                # SENSAI.md entre dans le prompt système : le modifier invalide aussi.
                self.cache.store(text, reply, [*sources, STATE_FILE], time.monotonic() - started)
            except (EmbeddingError, sqlite3.Error, OSError) as e:
                log.warning("réponse non mise en cache : %s", e)
        return [*turns, {"role": "user", "content": text}, {"role": "assistant", "content": reply}]
