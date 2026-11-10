"""
Base Loop entry point: CLI chatbot, streaming, session history, system
prompt loaded from a file, clean error handling, model selectable without
changing the code.

The CLI is the first interface to consume the agent's events
(core/events.py). The web interface (Workstream D) consumes exactly the same
ones, serialized as JSON — which guarantees both tell the same story.
See ADR-0005 and docs/architecture/web/api-contract.md.
"""
import atexit
import contextlib
import hashlib
import logging
import re
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import requests

from sensai import ui
from sensai.chat_commands import is_chat_command, run_chat_command
from sensai.config import get_settings, resolve_path
from sensai.core.agent import run_agent_turn
from sensai.core.answer import AnswerBuilder
from sensai.core.context_view import COMMAND as CONTEXT_COMMAND
from sensai.core.context_view import describe_context
from sensai.core.events import Done, Error, Event, Thought, Token, ToolCall, ToolReturn
from sensai.core.history import History
from sensai.core.ollama_client import (
    OllamaError,
    generation_options,
    set_generation_options,
    set_request_timeout,
    stream_chat,
)
from sensai.core.structured import StructuredOutputError, handle_structured_command
from sensai.execution.gateway import ConfirmationRequest, ToolGateway
from sensai.execution.guardrails import InputRules, check_input, filter_input, filter_output
from sensai.execution.sandbox.document_sandbox import DocumentSandbox
from sensai.knowledge.cache import CACHE_FILE, AnswerCache, handle_cache_command
from sensai.knowledge.compression import (
    DEFAULT_KEEP_RECENT,
    CompressionError,
    compress_messages,
    count_message_tokens,
    exceeds_budget,
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
    open_session,
)
from sensai.knowledge.persona import PersonaStore, handle_persona_command
from sensai.knowledge.rag import RAG_FILE, EmbeddingError, OllamaEmbedder, RagIndex, format_context
from sensai.knowledge.retrieval import LlmReranker
from sensai.knowledge.state_document import STATE_FILE, StateDocument, handle_state_command
from sensai.observability.journal import TurnRecorder, open_journal
from sensai.registry import build_registry
from sensai.tools.ask_user_tool import AskUserTool, terminal_asker
from sensai.tools.delegate_tool import DelegateTool
from sensai.tools.fact_tools import RecallFactsTool, RememberFactTool
from sensai.tools.mcp_tool import load_mcp_tools
from sensai.tools.project_tests import project_test_runner
from sensai.tools.rag_tool import RagTool
from sensai.tools.schedule_task_tool import ScheduleTaskTool
from sensai.tools.state_tool import UpdateStateTool
from sensai.tools.team_tool import TeamTool

_DEFAULT_STREAM_CHAT = stream_chat

log = logging.getLogger(__name__)


def describe_request(request: ConfirmationRequest) -> str:
    """Text shown before a risky action.

    Arguments are shown as plain text rather than through `request.summary`,
    which serializes them as JSON: the user is asked to approve code, so it
    must read exactly as it will run, line breaks included.
    """
    lines = [f"The agent wants to use the tool \"{request.tool}\" (risk: {request.risk.value})"]
    # A tool that describes its own action (`describe_call`: write_file's
    # diff, update_state's before/after) shows what will change; the
    # gateway's default summary, `tool({...})` as JSON, is replaced by the
    # plain arguments.
    if request.summary and not request.summary.startswith(f"{request.tool}("):
        lines.append(request.summary)
    else:
        lines += [f"  {key} = {value}" for key, value in request.arguments.items()]
    return "\n".join(lines)


def confirm_in_terminal(request: ConfirmationRequest) -> bool:
    """CLI version of the confirmation before a risky action (ADR-0005, ADR-0006).

    The web provides its own version, with a button. The gateway does not
    know which one it uses — that is the whole point.
    """
    title, _, details = describe_request(request).partition("\n")
    return ui.confirm(title, details or "(no details)")


def render(event: Event) -> str:
    """Turn an event into terminal text.

    Returns what to print, without a trailing newline: the caller decides
    the formatting, so Tokens stay glued together while streaming.
    """
    if isinstance(event, Token):
        return event.text
    if isinstance(event, Thought):
        return f"\n  … {event.text}\n"
    if isinstance(event, ToolCall):
        return f"\n  → {event.name}({event.arguments})\n"
    if isinstance(event, ToolReturn):
        marque = "✓" if event.ok else "✗"
        return f"  {marque} {event.name}: {event.content}\n"
    if isinstance(event, Error):
        return f"\n[Error] {event.message}\n"
    if isinstance(event, Done) and event.reason == "max_iterations":
        # Without this message, a cut-off turn looks like an empty answer.
        return "\n[Stopped] Maximum number of steps reached without a final answer.\n"
    return ""  # normal Done: nothing to print, the loop returns


def preload_model(host: str, model: str, num_ctx: int | None = None) -> None:
    """Load the model into server memory before the first question.

    Otherwise the first call waits for the load (about 80 s for
    qwen3-coder:30b) and exceeds the client timeout. On failure we warn and
    carry on: the first question will retry.

    `num_ctx` (M2, ADR-0045): Ollama reloads the model when a request's
    window differs from the one it was loaded with; warming up with the same
    one avoids that second load on the first question.
    """
    payload: dict = {"model": model, "prompt": ""}
    if num_ctx:
        payload["options"] = {"num_ctx": num_ctx}
    with ui.loading(f"Loading model {model}…"):
        try:
            requests.post(f"{host}/api/generate", json=payload,
                          timeout=300).raise_for_status()
        except requests.RequestException as e:
            ui.warn(f"(warning: the model could not be preloaded — {e})")


def _short_path(path: str) -> str:
    """The project shown in the banner, with ~ for the home directory."""
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home) else path


def open_rag_index(settings: dict, data_dir: Path, project: str) -> RagIndex:
    """Open the project index and update it (feature R1, ADR-0009).

    Called on the session's first question, not at startup: a new project
    takes several minutes to index, which we do not impose on someone who
    only uses commands. On later runs, only modified files are reprocessed.
    """
    rag_model = settings["rag_model"]
    # PDFs and Office documents are converted in the sandbox (ADR-0034).
    index = RagIndex(
        data_dir / RAG_FILE,
        project,
        OllamaEmbedder(settings["host"], rag_model),
        model=rag_model,
        converter=DocumentSandbox(),
    )
    if settings.get("rag_rerank", True):
        index.reranker = LlmReranker(
            settings["host"], settings["model"], num_ctx=settings.get("num_ctx")
        )
    ui.info(f"Indexing the project for search ({rag_model})...")

    def progress(done: int, total: int) -> None:
        print(f"\r  {done}/{total} files", end="", flush=True)

    report = index.update(Path(project), progress=progress)
    if report.files_indexed:
        print()
    ui.info(f"Project index up to date: {report.chunks} passages "
            f"({report.files_indexed} file(s) indexed, {report.files_removed} removed).")
    if report.unsupported:
        ui.warn("Files not indexed (unsupported format):")
        for path, advice in report.unsupported:
            ui.plain(f"  {path.relative_to(project)} — {advice}", "dim")
    return index


# Tools after which an answer may be cached (A6, ADR-0033): they read the
# project, and the files read are tracked to invalidate the answer. After any
# other tool (write, execution, web, fact memory), the answer is not kept.
# list_files (ADR-0059) only reads: without it, an answer that had listed
# files never entered the cache (rehearsal of 2026-11-06).
CACHEABLE_TOOLS = {"read_file", "list_files", "search_codebase"}
_PASSAGE_SOURCE = re.compile(r"^--- (.+?):\d+-\d+$", re.MULTILINE)


def open_answer_cache(settings: dict, data_dir: Path, project: str) -> AnswerCache | None:
    """Answer cache (A6); None if disabled or unreadable."""
    if not settings.get("cache", False):
        return None
    try:
        return AnswerCache(data_dir / CACHE_FILE, project,
                           OllamaEmbedder(settings["host"], settings["rag_model"]),
                           model=settings["model"])
    except (sqlite3.Error, OSError) as e:
        ui.warn(f"(warning: answer cache disabled — {e})")
        return None


def open_fewshot_index(settings: dict, host: str) -> FewShotIndex | None:
    """Few-shot examples (A7, ADR-0044); None if not configured or unreadable.

    Loaded once at startup, not on the first question like RAG: the examples
    file is small and the embedder handles it in an instant.
    """
    configured = settings.get("fewshot_examples")
    if not configured:
        return None
    # Same rule as config.json itself (resolve_path): relative to the
    # current directory, else to the repository root, not only to the
    # working directory (PR #96 review).
    path = resolve_path(configured)
    if path is None:
        ui.warn(f"(warning: few-shot examples disabled — file not found: "
                f"{configured})")
        return None
    index = FewShotIndex(
        OllamaEmbedder(host, settings["rag_model"]), settings["fewshot_min_score"]
    )
    try:
        count = index.load(path)
    except (FewShotError, EmbeddingError) as e:
        ui.warn(f"(warning: few-shot examples disabled — {e})")
        return None
    ui.info(f"Few-shot examples loaded ({count}) for automatic selection (A7).")
    return index


def _relative(path: str, project: str) -> str:
    try:
        return str(Path(project, path).resolve().relative_to(project))
    except ValueError:
        return path


def _run_turn(
    host: str, model: str, messages: list[dict], tools: ToolGateway,
    num_ctx: int | None = None, max_iterations: int | None = None,
):
    """Test compatibility: if `stream_chat` is mocked, replay the legacy stream."""
    if stream_chat is not _DEFAULT_STREAM_CHAT:
        try:
            for chunk in stream_chat(host, model, messages):
                yield Token(text=chunk)
        except OllamaError as e:
            yield Error(message=str(e))
            yield Done(reason="error")
            return
        yield Done()
        return
    yield from run_agent_turn(host, model, messages, tools, num_ctx=num_ctx,
                              max_iterations=max_iterations)


def main() -> None:
    settings = get_settings()
    model = settings["model"]
    host = settings["host"]
    # Context window sent to Ollama (M2, ADR-0045): without it, Ollama
    # silently truncates to its own default, before the token budget even
    # gets a chance to summarize anything.
    num_ctx = settings.get("num_ctx")
    # Generation parameters (ADR-0057): applied to every chat call.
    set_generation_options(settings.get("generation"))
    set_request_timeout(settings.get("request_timeout"))

    # --- Cross-session memory (feature M1, ADR-0007) ---
    data_dir = Path(settings["data_dir"]).expanduser() if settings["data_dir"] else None
    data_dir = data_dir or default_data_dir()
    project = str(Path.cwd().resolve())
    db_path = data_dir / SESSIONS_FILE
    store: SessionStore | None
    try:
        store = SessionStore(db_path)
    except sqlite3.Error as e:
        # Unreadable database: do not overwrite it (it may hold recoverable
        # conversations) and work without history.
        ui.warn(f"(warning: {db_path} unreadable ({e}) — history disabled "
                "for this session, the database was not modified)")
        store = None
    profile_path = data_dir / PROFILE_FILE
    try:
        profile = Profile.load(profile_path)
    except ValueError as e:
        # A broken profile must not prevent work: warn and start without it
        # instead of crashing.
        ui.warn(f"(warning: {e} — starting with an empty profile)")
        profile = Profile()
    retention_days = settings["retention_days"]
    session_id, turns = "", []
    if store is not None:
        # Purge before resuming: a session idle for more than
        # `retention_days` days is not resumed, and the user is told (ADR-0007).
        try:
            purged = store.purge(retention_days, keep=settings["session"])
        except sqlite3.Error as e:
            ui.warn(f"(warning: could not purge old sessions — {e})")
            purged = 0
        if purged:
            pluriel = "s" if purged > 1 else ""
            ui.info(f"{purged} session{pluriel} with no message for more than "
                    f"{retention_days} days deleted (--retention-days to change).")
        try:
            session_id, turns = open_session(
                store, project, session_id=settings["session"], new=settings["new_session"]
            )
        except KeyError:
            ui.error(f"[Error] Unknown session: {settings['session']}. It may have been "
                     f"purged (no message for more than {retention_days} days) "
                     "or the id is mistyped — see /sessions.")
            return

    # Rules added in config.json (EV2, ADR-0027): a malformed rule stops
    # startup rather than letting the user believe a topic is blocked.
    try:
        input_rules = InputRules.from_config(settings.get("input_blocklist"))
    except ValueError as e:
        ui.error(f"[Error] Configuration: {e}")
        return

    base_prompt = settings["system_prompt"]
    # The resume instruction is only sent if the history comes from a previous
    # session: that is when the model tends to deny remembering it.
    resumed_note = settings["memory_prompt"] if turns else ""

    # --- Project state document (feature M4, ADR-0029) ---
    # Change log kept outside the project, one file per project.
    project_key = hashlib.sha256(project.encode("utf-8")).hexdigest()[:16]
    state = StateDocument(project, data_dir / "state" / f"{project_key}.jsonl")
    try:
        state.purge(retention_days)
    except (OSError, ValueError) as e:
        ui.warn(f"(warning: could not purge the {state.path.name} log — {e})")

    # --- Turn log (EV3, ADR-0053): the same file as the web server ---
    journal = open_journal(data_dir)
    if journal is not None:
        try:
            journal.purge(retention_days)
        except (OSError, sqlite3.Error) as e:
            ui.warn(f"(warning: could not purge the turn log — {e})")

    # --- Structured fact memory (feature M3, ADR-0030) ---
    facts = FactStore(data_dir / FACTS_FILE, project)

    # --- Agent persona (feature A5, ADR-0042) ---
    # Just a label kept in memory: changing it never touches history.turns,
    # so the conversation context is not lost.
    # The fallback is never taken via get_settings() (its dict always has
    # "personas"): it protects tests that build `settings` by hand without
    # that key (tests/test_cli_rag.py and friends).
    personas = settings.get("personas") or PersonaStore.from_config(None)
    active_persona_id = personas.default_id
    # True only if the last persona change came from automatic routing
    # (A5, ADR-0043), not from an explicit /persona use: used to fall back to
    # the default persona when no keyword matches any more, without ever
    # undoing a choice the user made.

    # Session start time, kept for every turn (date_block).
    session_start = local_datetime()

    def system_prompt() -> str:
        """Rebuilt every turn: a SENSAI.md update, a remembered fact, a
        /remember, a /persona use or a manual edit apply from the next turn."""
        try:
            known = facts.as_prompt()
        except (OSError, sqlite3.Error) as e:
            ui.warn(f"(warning: fact memory unreadable — {e})")
            known = ""
        persona_prompt = personas.get(active_persona_id).as_prompt()
        return build_system_prompt(base_prompt, profile, resumed_note, now=session_start,
                                   extra=(persona_prompt, state.as_prompt(), known))

    history = History(system_prompt=system_prompt(), turns=turns)

    # Stateless tools are registered in sensai/registry.py, shared with the
    # scheduler (X5): see CONTRIBUTING.md.
    registry = build_registry(settings.get("file_permissions"))
    # Tools from the MCP servers in config.json (T1, ADR-0041): a failing
    # server is reported, the agent still starts with the other tools.
    mcp_tools, mcp_warnings, close_mcp = load_mcp_tools(settings.get("mcp_servers") or {})
    atexit.register(close_mcp)
    for tool in mcp_tools:
        registry.register(tool)
    for warning in mcp_warnings:
        ui.warn(f"(warning: {warning})")
    # Project search depends on the index opened by this session
    # (ADR-0013): it stays here and is therefore not offered to the scheduler.
    # It keeps its own passage count: --rag-top-k only limits the automatic
    # attachment on each question.
    rag_tool = RagTool(min_score=settings["rag_min_score"])
    if settings["rag"]:
        registry.register(rag_tool)
    # State document (M4): bound to this session's project, like RAG.
    registry.register(UpdateStateTool(state))
    # Fact memory (M3): remember (confirmed) and recall; no deletion.
    registry.register(RememberFactTool(facts))
    registry.register(RecallFactsTool(facts))
    # The agent only gets the gateway: it applies permissions, guardrails
    # and confirmation on every call (ADR-0006).
    # Without the EV2 guardrails, a secret read by a tool reached the model
    # in clear text (EV4, OUT-15).
    tools = ToolGateway(
        registry,
        settings.get("tool_preferences"),
        confirm=confirm_in_terminal,
        input_guards=[check_input],
        output_filters=[filter_output],
    )
    # Sub-agent delegation (A2, ADR-0037): added after the gateway because
    # the tool uses it to run the sub-agent — with the same permissions,
    # guardrails and confirmations as the main agent.
    delegate = DelegateTool(host, model, tools, system_prompt=system_prompt, num_ctx=num_ctx)
    delegate.timeout_s = tools.preferences.delegation_timeout_s
    registry.register(delegate)
    # Team of specialized agents (A2, ADR-0038): every handoff is shown.
    team = TeamTool(delegate, notify=ui.info, test_runner=project_test_runner(project))
    team.timeout_s = tools.preferences.delegation_timeout_s
    registry.register(team)
    # Agent questions (X4, ADR-0046): asked in the terminal.
    registry.register(AskUserTool(terminal_asker()))
    # Natural-language scheduling (X5, ADR-0052): always with explicit consent.
    registry.register(ScheduleTaskTool(data_dir))

    # Per-persona tool restriction (A5, ADR-0043): a persona can only ADD
    # disabled tools to those already denied by config.json, never re-allow
    # one — the base stays the user's policy.
    base_tool_preferences = tools.preferences

    def apply_persona_tools() -> None:
        extra = personas.get(active_persona_id).tools_disabled
        tools.preferences = (
            replace(base_tool_preferences, disabled=base_tool_preferences.disabled | extra)
            if extra else base_tool_preferences
        )

    apply_persona_tools()

    lines = [("model", model), ("server", host), ("project", _short_path(project))]
    if turns:
        lines.append(("session", f"{session_id} resumed ({len(turns)} messages) "
                                 "· --new-session to start over"))
    elif store is not None:
        lines.append(("session", f"{session_id} (new)"))
    # Prompt versions in use (feature A4, ADR-0010): to know which prompt
    # produced this session's answers.
    prompt_versions = settings.get("prompt_versions") or {}
    if prompt_versions:
        lines.append(("prompts", ", ".join(f"{k} {v}" for k, v in prompt_versions.items())))
    if len(personas.names()) > 1:
        lines.append(("persona", f"{personas.get(active_persona_id).name} (/persona to change)"))
    notes = []
    if not base_prompt:
        notes.append("(warning: no system prompt loaded — see: sensai-prompt check)")
    ui.banner(lines, notes)
    prompt = ui.Prompt(data_dir / "cli_history")
    if ui.interactive():
        # The first load of a large model exceeds the client timeout (60 s):
        # do it here, with a visible wait (real trial runs).
        preload_model(host, model, num_ctx=num_ctx)

    # --- Project search (feature R1, ADR-0009) ---
    rag_on = settings["rag"]
    rag_index: RagIndex | None = None

    # --- Answer cache (feature A6, ADR-0033) ---
    cache = open_answer_cache(settings, data_dir, project)
    last_question = ""

    def ensure_rag_index() -> RagIndex:
        """Open the project index on first need, then keep it up to date.

        Shared by the chat loop and `/structured`: the `search_codebase` tool
        only has an index once it is open. Without this, a `/structured` typed
        before any question answered "project not indexed" and the agent
        guessed file names (trial run of 2026-11-06, T5)."""
        nonlocal rag_index
        if rag_index is None:
            rag_index = open_rag_index(settings, data_dir, project)
            rag_tool.index = rag_index
        else:
            # Files created or modified since opening (often by the agent):
            # at most one update every 30 s.
            rag_index.refresh_if_stale(Path(project))
        return rag_index

    def gather_for_structured(question: str) -> str:
        """Two-step T5 (ADR-0039): the agent searches with its tools, through the
        same gateway (same confirmations), before the schema formatting."""
        if rag_on:
            try:
                ensure_rag_index()
            except (EmbeddingError, sqlite3.Error, OSError) as e:
                ui.warn(f"(warning: project search unavailable — {e})")
        view = ui.TurnView()
        found = ""
        messages = [{"role": "system", "content": system_prompt()},
                    {"role": "user", "content": question}]
        for event in _run_turn(host, model, messages, tools, num_ctx=num_ctx,
                               max_iterations=settings.get("max_iterations")):
            view.show(event)
            if isinstance(event, Token):
                found += event.text
            elif isinstance(event, Error):
                raise StructuredOutputError(event.message)
        return found

    # --- Automatic few-shot examples (feature A7, ADR-0044) ---
    fewshot_index = open_fewshot_index(settings, host)

    def save_session() -> None:
        if store is not None:
            try:
                store.save(session_id, history.turns)
            except sqlite3.Error as e:
                ui.warn(f"(warning: could not save the session — {e})")

    while True:
        # "No, and say what to do" on a confirmation: the instruction is sent as
        # the next message, without retyping it.
        instruction = ui.take_instruction()
        if instruction:
            ui.plain(f"> {instruction}", "dim")
            user_input = instruction
        else:
            try:
                user_input = prompt.read().strip()
            except (EOFError, KeyboardInterrupt):
                ui.info("\nGoodbye.")
                break

        if not user_input:
            ui.info("(empty input ignored, type something)")
            continue
        if user_input.lower() in ("exit", "quit"):
            break
        if user_input == "/help":
            ui.plain(ui.HELP)
            continue

        # Before anything else: a command like /remember writes to the profile,
        # and the question goes to the model, the RAG index and the saved session.
        # A failing filter blocks, it does not let through (like the gateway).
        try:
            allowed, user_input = filter_input(user_input, input_rules)
        except Exception:
            log.exception("input filter failed")
            allowed, user_input = False, "the input filter failed"
        if not allowed:
            ui.error(f"[Blocked] {user_input}")
            continue

        # /schedule (X5) and /eval (EV1): the sensai-schedule and sensai-eval
        # commands without leaving the chat (ADR-0028). Nothing is sent to the
        # model or kept in the session.
        if is_chat_command(user_input):
            run_chat_command(
                user_input, host=host, model=model, data_dir=settings["data_dir"]
            )
            continue

        # /structured (T5): a single JSON-schema-constrained call, without the
        # agent loop (ADR-0036). Nothing is sent to the chat model or kept in
        # the session.
        structured_output = handle_structured_command(
            user_input, host=host, model=model, gather=gather_for_structured, num_ctx=num_ctx
        )
        if structured_output is not None:
            ui.plain(structured_output)
            continue

        state_output = handle_state_command(user_input, state)
        if state_output is not None:
            ui.plain(state_output)
            continue

        persona_result = handle_persona_command(user_input, personas, active_persona_id)
        if persona_result is not None:
            persona_output, active_persona_id = persona_result
            apply_persona_tools()
            ui.plain(persona_output)
            continue

        facts_output = handle_facts_command(user_input, facts)
        if facts_output is not None:
            ui.plain(facts_output)
            continue

        if user_input.strip() == CONTEXT_COMMAND:
            # What would go to the model now (ADR-0058): rebuilt system prompt,
            # history, parameters sent to Ollama.
            history.system_prompt = system_prompt()
            ui.plain(describe_context(history.as_messages(), num_ctx,
                                      settings.get("token_budget_max"), generation_options()))
            continue

        cache_output = handle_cache_command(user_input, cache)
        if cache_output is not None:
            ui.plain(cache_output)
            continue
        skip_cache = False
        if user_input == "/again":
            if not last_question:
                ui.info("(no question to ask again)")
                continue
            user_input, skip_cache = last_question, True
            ui.plain(f"> {user_input}", "dim")
            if cache is not None:
                cache.forget(user_input)

        try:
            command_output = handle_command(user_input, profile, profile_path, store, project)
        except (OSError, sqlite3.Error) as e:
            ui.error(f"[Error] Command failed: {e}")
            continue
        if command_output is not None:
            ui.plain(command_output)
            continue

        # A persona that restricts tools (A5, ADR-0043) neither reads nor
        # feeds the cache (A6): an answer cached under a permissive persona
        # could depend on a tool this one forbids — serving it anyway would
        # bypass the restriction unnoticed (PR #95 review). Computed after the
        # routing above, so on the persona actually used for this turn.
        cache_usable = cache is not None and not personas.get(active_persona_id).tools_disabled

        # A question already handled gets the cached answer, without calling
        # the chat model; at the slightest doubt, the cache does not answer (ADR-0033).
        hit = None
        if cache_usable and not skip_cache:
            try:
                hit = cache.lookup(user_input)
            except (EmbeddingError, sqlite3.Error, OSError, ValueError) as e:
                ui.warn(f"(warning: answer cache disabled for this session — {e})")
                cache = None
        if hit is not None:
            ui.cached_answer(hit.answer, hit.question, hit.created_at, hit.similarity)
            last_question = user_input
            history.add_user(user_input)
            history.add_assistant(hit.answer)
            save_session()
            continue

        context = None
        sources: list[str] = []
        if rag_on:
            try:
                ensure_rag_index()
                hits = rag_index.search(
                    user_input, top_k=settings["rag_top_k"], min_score=settings["rag_min_score"]
                )
                # Same guardrails as tool outputs (EV2): without them, a key read
                # in the project reached the model in clear text (trial run of 2026-10-24).
                context = filter_output(format_context(hits))
                sources = [h["source"] for h in hits]
            except (EmbeddingError, sqlite3.Error, OSError) as e:
                # Without embeddings the assistant is still useful: carry on without search.
                ui.warn(f"(warning: project search disabled for this "
                        f"session — {e})")
                rag_on = False

        # Automatic few-shot (A7, ADR-0044): nothing is added if no example is
        # close enough — unlike RAG, a doubtful few-shot would mislead the model
        # more than its absence would hurt.
        fewshot_block = None
        if fewshot_index is not None:
            try:
                example = fewshot_index.best_match(user_input)
            except EmbeddingError as e:
                ui.warn(f"(warning: few-shot examples disabled for this "
                        f"session — {e})")
                fewshot_index = None
                example = None
            if example is not None and not worth_attaching(example, user_input,
                                                           profile.preferences):
                example = None
            if example is not None:
                # Same guardrail as for RAG (EV2): the examples file may come
                # from a real session, with a secret in its answer; and
                # "good answer to follow" is an open door to instruction
                # injection without this filter (PR #96 review).
                fewshot_block = filter_output(format_example(example, profile.preferences))

        history.system_prompt = system_prompt()
        history.add_user(user_input)
        messages = history.as_messages()
        if context or fewshot_block:
            # The few-shot and the passages go with the question sent to the
            # model, but not into the saved history: otherwise every session
            # would grow with content already stale by the next turn.
            prelude = "\n\n".join(p for p in (fewshot_block, context) if p)
            messages[-1] = {"role": "user", "content": f"{prelude}\n\nQuestion: {user_input}"}

        if settings.get("token_budget", True):
            # Token budget and rolling summary (M2, ADR-0045): AFTER adding
            # RAG and few-shot above, not before — otherwise the budget would
            # not count what actually goes to the model (PR #97 review). Only
            # the messages SENT this turn are compacted, never history.turns
            # or the saved session (M1) — resuming later finds the history intact.
            try:
                messages, compressed = compress_messages(
                    host, model, messages,
                    max_tokens=settings.get("token_budget_max"),
                    keep_recent=settings.get("token_budget_keep_recent", DEFAULT_KEEP_RECENT),
                    num_ctx=num_ctx,
                )
            except CompressionError as e:
                ui.warn(f"(warning: automatic history summary "
                        f"failed for this turn — {e})")
            else:
                if compressed:
                    ui.info("(older history summarized to stay within the token budget)")
                elif exceeds_budget(messages, settings.get("token_budget_max"), num_ctx):
                    # Nothing to summarize (a last message bloated by RAG alone, or
                    # fewer turns than keep_recent): it goes as is, but we warn
                    # rather than let Ollama truncate silently.
                    ui.warn("(warning: this turn's context exceeds the token "
                            "budget and cannot be summarized — Ollama may truncate it)")

        reponse_builder = AnswerBuilder()
        echec = False
        cacheable = True
        started = time.monotonic()
        view = ui.TurnView()
        # EV3: main-agent tools and model time (not yet sub-agents in the
        # terminal); a log failure does not cut the turn.
        recorder = TurnRecorder(journal, session_id=session_id or None, project=project,
                                interface="cli", tokens_sent=count_message_tokens(messages))
        turn = _run_turn(host, model, messages, tools, num_ctx=num_ctx,
                         max_iterations=settings.get("max_iterations"))
        try:
            with ui.EscWatcher() if ui.interactive() else contextlib.nullcontext() as esc:
                for event in turn:
                    view.show(event)
                    recorder.on_event(event)
                    if isinstance(event, Token):
                        reponse_builder.add(event.text)
                    elif isinstance(event, Error):
                        echec = True
                    elif isinstance(event, ToolCall):
                        reponse_builder.tool_boundary()
                        if event.name not in CACHEABLE_TOOLS:
                            cacheable = False
                        elif event.name == "read_file" and event.arguments.get("path"):
                            sources.append(_relative(str(event.arguments["path"]), project))
                    elif isinstance(event, ToolReturn) and event.name == "search_codebase":
                        sources += _PASSAGE_SOURCE.findall(event.content)
                    if esc is not None and esc.pressed.is_set():
                        raise KeyboardInterrupt
        except KeyboardInterrupt:
            # Esc or Ctrl+C: stop the turn (and the model request); the
            # question is dropped as for a failed turn.
            turn.close()
            view.interrupted()
            echec = True
            recorder.finish("interrupted")
        finally:
            view.close()
            recorder.finish()

        if echec:
            # The turn is lost: drop the question so no unanswered user turn
            # stays in the model's context.
            history.drop_last()
            continue

        reponse = reponse_builder.text()
        history.add_assistant(reponse)
        save_session()
        last_question = user_input
        # The persona is fixed before the cache (routing above) and does not
        # change during the turn: `cache_usable` also applies to writing.
        if cache is not None and cache_usable and cacheable:
            # SENSAI.md goes into the system prompt: editing it also invalidates.
            try:
                cache.store(user_input, reponse, [*sources, STATE_FILE],
                            time.monotonic() - started)
            except (EmbeddingError, sqlite3.Error, OSError) as e:
                ui.warn(f"(warning: answer not cached — {e})")


if __name__ == "__main__":
    main()
