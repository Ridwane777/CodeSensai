"""
[Workstream D] The web server's agent: the same parts as the CLI (ADR-0035).

One `WebRuntime` per server, for the project `sensai-web` is launched from. It
assembles what `cli.main` assembles: shared registry, project search (R1, R2),
state document (M4), fact memory (M3), gateway with guardrails (EV2), input
filter, semantic cache (A6) and sessions (M1). The CLI is unchanged;
`tests/web/test_runtime.py` checks that both offer the same tools.

`run_turn` plays a turn and publishes dictionaries ready for the SSE stream:
the Workstream A stream (`to_wire`) and the ADR-0024 extensions that only the
server produces (`rag_sources`, `cache_hit`, `guardrail`,
`done.reason = "interrupted"`). It runs in a worker thread: web confirmation
blocks that thread (ADR-0015, ADR-0022).
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

# Like the CLI (A6, ADR-0033): only an answer based on these project-reading
# tools can be cached.
# list_files (ADR-0059) only reads: without it, an answer that had listed
# files never entered the cache (rehearsal of 2026-11-06).
CACHEABLE_TOOLS = {"read_file", "list_files", "search_codebase"}
_PASSAGE_SOURCE = re.compile(r"^--- (.+?):\d+-\d+$", re.MULTILINE)
# web_search results ("1. title" then the URL, see web_search_tool._format):
# the UI's Sources tab lists them (US-T3-1). http(s) links only.
_WEB_RESULT = re.compile(r"^\d+\. (.+)\n {3}(https?://\S+)$", re.MULTILINE)
# /schedule and /eval print to the terminal (ADR-0028): not available on the web.
TERMINAL_ONLY = ("/schedule", "/eval")
# The main agent in `agent_handoff` events (X1, A2); the UI replaces it with
# the name of the displayed persona.
MAIN_AGENT = "main"
DELEGATION_TOOLS = {"delegate_task", "team_task"}
# What is shown of a sub-agent's tool result: a preview, not the whole file read.
SUBAGENT_STEP_CHARS = 600


class Handoffs:
    """Tracks which agent has control during a turn and publishes each handoff.

    Announced when the sub-agent really starts (after confirmation), never on
    the model's request alone: a refused delegation shows no handoff.
    Simple delegation: one handoff out (to the role, or "sous-agent") and one back.
    Team: one handoff per role (explorer → developer → reviewer…), then back to
    the main agent when the tool ends.
    """

    def __init__(self, emit: Emit, recorder: TurnRecorder | None = None) -> None:
        self.emit = emit
        self.current = MAIN_AGENT
        # EV3 log: every sub-agent tool is recorded there with its duration.
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
        """A tool run by the sub-agent in control (A2): the UI shows it in the turn's
        reasoning. The content is already filtered by the gateway (EV2).
        `duration_ms`: measured server-side around the call (EV3)."""
        event = {"type": "subagent_step", "agent": self.current, "tool": tool,
                 "arguments": arguments, "ok": ok, "content": content[:SUBAGENT_STEP_CHARS]}
        if duration_ms is not None:
            event["duration_ms"] = duration_ms
        self.emit(event)
        if self.recorder is not None:
            self.recorder.subagent_call(tool, arguments, ok, duration_ms or 0, self.current)


class _Timed:
    """Wraps the gateway seen by sub-agents to time each call (EV3); the
    sub-agent calls tools in the turn's thread, one at a time."""

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
    """`delegate_task` that announces the handoff when the sub-agent starts."""

    def __init__(self, *args: Any, handoffs: Handoffs | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.handoffs = handoffs
        self.tools = _Timed(self.tools)

    def run(self, **kwargs: Any):
        if self.handoffs is not None and str(kwargs.get("task") or "").strip():
            self.handoffs.to(str(kwargs.get("role") or "sous-agent"))
        return super().run(**kwargs)

    def delegate(self, task: str, *, on_call=None, **kwargs: Any):
        """Every sub-agent tool is also published (A2), including for the team
        (`team_task` calls this method for each role)."""
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
    """The agent and its memories for one project, shared by all web sessions."""

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
        # M2 (ADR-0045): like the CLI, the context window is sent with every model
        # call; without it, Ollama silently truncates to its default value.
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
        # Share links (X3, ADR-0048), next to the sessions.
        self.shares = ShareStore(self.data_dir / SHARES_FILE)
        # Scheduled tasks (X5): the same file as `sensai-schedule`, which runs them.
        self.tasks = TaskStore(self.data_dir / "schedule" / TASKS_FILE)
        # Turn log (EV3, ADR-0053): None if it cannot be opened, the chat goes on.
        self.journal = open_journal(self.data_dir)
        self.profile_path = self.data_dir / PROFILE_FILE
        try:
            self.profile = Profile.load(self.profile_path)
        except ValueError as e:
            log.warning("unreadable profile, starting with an empty profile: %s", e)
            self.profile = Profile()
        # A malformed rule stops startup (like the CLI, ADR-0027).
        self.input_rules = InputRules.from_config(settings.get("input_blocklist"))
        key = hashlib.sha256(self.project.encode("utf-8")).hexdigest()[:16]
        self.state = StateDocument(self.project, self.data_dir / "state" / f"{key}.jsonl")
        self.facts = FactStore(self.data_dir / FACTS_FILE, self.project)
        self.rag_tool = RagTool(min_score=settings["rag_min_score"])
        self.rag_on = bool(settings["rag"])
        self.rag_index: RagIndex | None = None
        self.notices: list[str] = []  # warnings to show in the UI
        # MCP servers (T1, ADR-0041): started once for the whole web server, their
        # tools added to every gateway; a failure becomes a warning.
        self.mcp_tools, mcp_warnings, self.close_mcp = load_mcp_tools(
            settings.get("mcp_servers") or {})
        atexit.register(self.close_mcp)
        self.notices += mcp_warnings
        self._rag_lock = threading.Lock()
        self._profile_lock = threading.Lock()
        self.cache = self._open_cache()
        self._fewshot: FewShotIndex | None = None
        self._fewshot_off = False
        # Personas (A5, ADR-0042/0043; web: ADR-0054). Like the CLI: the active
        # persona is only an in-memory label, here one per conversation; nothing is
        # saved, a reopened conversation starts again from the default persona.
        self.personas: PersonaStore = settings.get("personas") or PersonaStore.from_config(None)
        # Prompt registry (A4, ADR-0010; web: ADR-0055): read, never written by the
        # server. A version trial applies to one conversation only, in memory.
        self.prompt_store = prompt_store or PromptStore(prompts_dir())
        self._session_persona: dict[str, str] = {}
        self._session_prompt_trial: dict[str, str] = {}
        # Time of each conversation's first turn: frozen in the system prompt,
        # otherwise it would change every turn and Ollama would reread the whole conversation.
        self._session_started: dict[str, datetime] = {}
        self._session_lock = threading.Lock()

    # --- Startup -----------------------------------------------------------------

    def _open_cache(self) -> AnswerCache | None:
        if not self.settings.get("cache", False):
            return None
        try:
            return AnswerCache(self.data_dir / CACHE_FILE, self.project,
                               self._embedder_factory(self.host, self.settings["rag_model"]),
                               model=self.model)
        except (sqlite3.Error, OSError) as e:
            self.notices.append(f"Answer cache disabled: {e}")
            return None

    def purge(self) -> int:
        """Sessions and state log that are too old (M1, M4); issue #65."""
        days = self.settings["retention_days"]
        try:
            self.state.purge(days)
        except (OSError, ValueError) as e:
            log.warning("could not purge the state log: %s", e)
        if self.journal is not None:
            try:
                self.journal.purge(days)
            except (OSError, ValueError, sqlite3.Error) as e:
                log.warning("could not purge the EV3 log: %s", e)
        try:
            self.shares.purge()
        except (OSError, ValueError) as e:
            log.warning("could not purge share links: %s", e)
        try:
            return self.store.purge(days)
        except sqlite3.Error as e:
            log.warning("could not purge sessions: %s", e)
            return 0

    def ensure_index(self) -> RagIndex | None:
        """Opens and updates the project index on the first question, then keeps it
        up to date as questions come (like the CLI)."""
        if not self.rag_on:
            return None
        with self._rag_lock:
            if self.rag_index is not None:
                # Files created or modified since (often by the agent) enter the
                # search; at most one update every 30 s.
                try:
                    self.rag_index.refresh_if_stale(Path(self.project))
                except (EmbeddingError, sqlite3.Error, OSError) as e:
                    self._notice(f"Project index not updated: {e}")
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
                self.notices.append(f"Project search disabled: {e}")
                return None
            for path, advice in report.unsupported:
                self.notices.append(f"Not indexed: {_relative(str(path), self.project)} - {advice}")
            self.rag_index = index
            self.rag_tool.index = index
            return index

    # --- Persona and prompt trial, per conversation (ADR-0054, ADR-0055) --------

    def persona_of(self, session_id: str | None) -> Persona:
        with self._session_lock:
            persona_id = self._session_persona.get(session_id or "", self.personas.default_id)
        return self.personas.get(persona_id)

    def set_persona(self, session_id: str, persona_id: str) -> Persona:
        """PersonaError if the persona is unknown (the server turns it into a 404)."""
        persona = self.personas.get(persona_id)
        with self._session_lock:
            self._session_persona[session_id] = persona.id
        return persona

    def prompt_trial_of(self, session_id: str | None) -> str | None:
        with self._session_lock:
            return self._session_prompt_trial.get(session_id or "")

    def set_prompt_trial(self, session_id: str, version: str | None) -> str | None:
        """Trials a system prompt version in this conversation (None: back to the
        active version). KeyError if the version does not exist. The registry is
        only read: `PromptStore.use` stays reserved to `sensai-prompt use`."""
        with self._session_lock:
            if version is None:
                self._session_prompt_trial.pop(session_id, None)
                return None
        version_id = self.prompt_store.resolve("system", version)
        with self._session_lock:
            self._session_prompt_trial[session_id] = version_id
        return version_id

    def started_at(self, session_id: str | None) -> datetime:
        """The time of the conversation's first turn, kept in server memory."""
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
        """Like the CLI: prompt, resume instruction, profile, persona, SENSAI.md, facts.

        `prompt_version`: a registry version trialed in this conversation
        (ADR-0055) instead of the system prompt loaded at startup.
        """
        try:
            known = self.facts.as_prompt()
        except (OSError, sqlite3.Error) as e:
            log.warning("unreadable fact memory: %s", e)
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
        # X4 (ADR-0046): without a browser to answer (`asker` missing), the tool
        # still exists and replies "nobody can answer".
        registry.register(AskUserTool(asker))
        # Natural-language scheduling (X5, ADR-0052): always with explicit consent.
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
        # Like the CLI (A5, ADR-0043): a persona can only ADD disabled tools to
        # those of config.json, never re-enable one.
        persona = persona or self.personas.default()
        if persona.tools_disabled:
            base = gateway.preferences
            gateway.preferences = replace(base, disabled=base.disabled | persona.tools_disabled)
        # Like the CLI (A2, ADR-0037): the sub-agent goes through this same gateway
        # (so the same tools are refused) and gets the same prompt (persona included).
        delegate = _AnnouncedDelegate(self.host, self.model, gateway,
                                      system_prompt=lambda: self.system_prompt(
                                          resumed=False, persona=persona,
                                          prompt_version=prompt_version, started=started),
                                      num_ctx=self.num_ctx, handoffs=handoffs)
        delegate.timeout_s = gateway.preferences.delegation_timeout_s
        registry.register(delegate)
        team = TeamTool(delegate, on_handoff=handoffs.to if handoffs else None,
                        test_runner=project_test_runner(self.project))
        team.timeout_s = gateway.preferences.delegation_timeout_s
        registry.register(team)
        return gateway

    def command(self, text: str) -> str | None:
        """Chat commands (`/state`, `/facts`, `/cache`, `/remember`…), like the CLI."""
        if text.split()[0] in TERMINAL_ONLY:
            return "This command is only available in the terminal (sensai)."
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
        """Plays a turn and returns the history to save, or None if it does not change.

        Always ends with a `done`. An interrupted, failed or blocked turn, or a
        command, does not enter the history (like the CLI).
        """
        try:
            return self._turn(turns, text, emit, cancel, confirmer, skip_cache, asker,
                              session_id)
        except Exception:  # a bug must neither leave the stream open nor leak a traceback
            log.exception("agent turn failed")
            emit({"type": "error", "message": "Internal server error."})
            emit({"type": "done", "reason": "error"})
            return None

    def _within_budget(self, messages: list[dict], emit: Emit | None = None) -> list[dict]:
        """Token budget and rolling summary (M2, ADR-0045), like the CLI.

        Called AFTER adding the RAG to the question, and only the copy sent to
        the model is compacted: the turns saved in the session (M1) are never
        touched. A summary failure, or a context too large to reduce, becomes a
        UI warning, never a loss of history.
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
            self._notice(f"Automatic history summary failed for this turn: {e}")
            self._emit_usage(messages, max_tokens, emit)
            return messages
        if not compressed and exceeds_budget(messages, max_tokens, self.num_ctx):
            self._notice("A turn's context exceeds the token budget and cannot be "
                         "summarized: Ollama may truncate it.")
        if compressed and emit is not None:
            saved = count_message_tokens(messages) - count_message_tokens(compacted)
            emit({"type": "compression", "saved_tokens": max(saved, 0)})
        self._emit_usage(compacted, max_tokens, emit)
        return compacted

    def _emit_usage(self, messages: list[dict], max_tokens: int | None, emit: Emit | None) -> None:
        """M2: what is sent to the model this turn, in ESTIMATED tokens (characters / 4,
        ADR-0045), against the budget and the `num_ctx` window."""
        if emit is None:
            return
        used = count_message_tokens(messages)
        window = self.num_ctx or DEFAULT_NUM_CTX
        emit({"type": "usage", "used": used, "budget": resolve_budget(max_tokens, self.num_ctx),
              "num_ctx": window, "estimated": True})

    def evaluate(self, turns: list[dict]) -> dict[str, Any]:
        """On-demand EV1: has the last answer judged (relevance, coherence,
        faithfulness to project passages), with the `sensai-eval` judge.

        One extra model call: that is why it is not done on every turn. Without
        project search, faithfulness has no passages and is None. Raises
        ValueError if there is no answer to judge.
        """
        pairs = [(turns[i]["content"], turns[i + 1]["content"]) for i in range(len(turns) - 1)
                 if turns[i].get("role") == "user" and turns[i + 1].get("role") == "assistant"]
        if not pairs:
            raise ValueError("no answer to evaluate in this conversation")
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
            log.warning("unreadable state document: %s", e)
            return {}

    def ensure_fewshot(self) -> FewShotIndex | None:
        """Few-shot examples (A7), loaded on the first question; None if not configured."""
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
        """What the UI shows of A7: file, threshold, example questions.
        Loads the examples if not loaded yet (same path as a turn)."""
        configured = self.settings.get("fewshot_examples")
        info: dict[str, Any] = {"configured": bool(configured), "file": configured or None,
                                "min_score": self.settings.get("fewshot_min_score", 0.75),
                                "questions": [], "error": None}
        if not configured:
            return info
        index = self.ensure_fewshot()
        if index is None:
            info["error"] = next((n for n in reversed(self.notices) if "few-shot" in n),
                                 "few-shot examples disabled")
            return info
        info["questions"] = index.questions()
        return info

    def _fewshot_failed(self, reason: object) -> None:
        self._fewshot_off = True
        self._fewshot = None
        self._notice(f"few-shot examples disabled: {reason}")

    def _notice(self, text: str) -> None:
        """A UI warning, shown once even if the case repeats."""
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
            # What would be sent to the model in this conversation (ADR-0058): same
            # system prompt as the turn (persona, prompt trial, time), same history.
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

        # Fixed for the whole turn: the server refuses to change them during a turn (409).
        persona = self.persona_of(session_id)
        prompt_version = self.prompt_trial_of(session_id)
        # Like the CLI (ADR-0043): a persona that restricts tools neither reads nor
        # feeds the cache; nor does a prompt trial (ADR-0055) - an answer stored
        # under another prompt version says nothing about the one being trialed.
        cache_usable = (self.cache is not None and not persona.tools_disabled
                        and prompt_version is None)

        if cache_usable and not skip_cache:
            try:
                hit = self.cache.lookup(text)
            except (EmbeddingError, sqlite3.Error, OSError, ValueError) as e:
                self.notices.append(f"Answer cache disabled: {e}")
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
                self.notices.append(f"Project search disabled: {e}")
                hits = None
            if hits is not None:
                # Same guardrails as tool outputs (EV2): without them, a key read in
                # the project went to the model in clear text (trial run of 2026-10-24).
                context = filter_output(format_context(hits))
                sources = [h["source"] for h in hits]
                emit({"type": "rag_sources", "sources": [
                    {"path": h["source"], "lines": f"{h['start']}-{h['end']}", "score": h["score"]}
                    for h in hits]})

        # Automatic few-shot (A7, ADR-0044), like the CLI: nothing if no example is
        # close enough; filtered by the EV2 guardrails like the RAG.
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
        # EV3 log: timer started right before the model (RAG and summary excluded).
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
                # The handoff back to the main agent goes before the `tool_return` that
                # causes it: the UI shows the handoff, then the result.
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
                # M4: a state document section modified by the agent is sent to the
                # UI (Artifact panel), only if it changed.
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
                # SENSAI.md goes into the system prompt: modifying it also invalidates.
                self.cache.store(text, reply, [*sources, STATE_FILE], time.monotonic() - started)
            except (EmbeddingError, sqlite3.Error, OSError) as e:
                log.warning("answer not cached: %s", e)
        return [*turns, {"role": "user", "content": text}, {"role": "assistant", "content": reply}]
