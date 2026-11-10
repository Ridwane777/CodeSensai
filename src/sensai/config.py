"""
Configuration loading: model, Ollama host, system prompt path.

Priority: CLI argument > config.json > defaults.
None of this is hardcoded in the application logic.
"""
import argparse
import json
from pathlib import Path

from sensai.core.agent import MAX_ITERATIONS
from sensai.core.ollama_client import DEFAULT_REQUEST_TIMEOUT, GENERATION_KEYS
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.tool_policy import ToolPreferences
from sensai.knowledge.compression import DEFAULT_NUM_CTX, budget_from_num_ctx
from sensai.knowledge.persona import PersonaError, PersonaStore
from sensai.knowledge.prompt_versions import INDEX_FILE, PromptStore
from sensai.tools.mcp_tool import parse_mcp_config

# Repository root: config.py lives in src/sensai/, so two levels up.
# Without this, `config.json` and `prompts/` were only found when the command
# was run from the project folder — but `sensai` is an installed command, and a
# coding assistant is precisely launched from the user's own project.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG_PATH = "config.json"
# Dev model chosen in docs/research/model-choices.md: small enough to iterate fast,
# and it supports Ollama's native tool calling (required by ADR-0003).
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_SYSTEM_PROMPT_PATH = "prompts/system_prompt.txt"
# Instruction added when a session is resumed (feature M1, ADR-0007).
DEFAULT_MEMORY_PROMPT_PATH = "prompts/memory_prompt.txt"
# Session retention (ADR-0007): 30 days, like Claude Code.
DEFAULT_RETENTION_DAYS = 30
# RAG (ADR-0009): model and threshold chosen by measurement, docs/performance/R1-rag.md.
DEFAULT_RAG_MODEL = "bge-m3"
DEFAULT_RAG_MIN_SCORE = 0.54
DEFAULT_RAG_TOP_K = 5
# Automatic few-shot (A7, ADR-0044): stricter than RAG, but the threshold is ESTIMATED,
# not measured — see fewshot.py and scripts/bench_fewshot.py.
DEFAULT_FEWSHOT_MIN_SCORE = 0.75
# Token budget (M2, ADR-0045): DEFAULT_NUM_CTX (imported from compression.py)
# is the window sent to Ollama; the budget is derived from it (minus a reply
# margin) further down, once the command line has been read.
DEFAULT_TOKEN_BUDGET_KEEP_RECENT = 6
# Generation parameters sent to Ollama (ADR-0057). Low temperature: a coding
# assistant must give the same command, the same path, the same tool call from
# one run to the next. Values compared against the real model:
# docs/performance/generation-parameters.md (scripts/bench_generation.py).
DEFAULT_GENERATION = {"temperature": 0.2, "top_p": 0.9}


def resolve_path(path: str) -> Path | None:
    """
    Look for `path` first in the current directory (so a user can drop their own
    config.json next to their project), then in the repository root. Returns
    None if the file exists in neither.
    """
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None

    for root in (Path.cwd(), PROJECT_ROOT):
        resolved = root / candidate
        if resolved.is_file():
            return resolved
    return None


def load_config_file(path: str = DEFAULT_CONFIG_PATH) -> dict:
    resolved = resolve_path(path)
    if resolved is None:
        return {}
    with open(resolved, encoding="utf-8") as f:
        return json.load(f)


def generation_from_config(file_config: dict) -> dict:
    """Generation parameters from config.json, defaults included (ADR-0057), for
    commands that do not go through `get_settings()`. ValueError on an unknown key:
    a misspelled parameter must not pass for an active one."""
    section = file_config.get("generation") or {}
    unknown = set(section) - set(GENERATION_KEYS)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"config.json: unknown generation parameter: {names}")
    return {k: v for k, v in {**DEFAULT_GENERATION, **section}.items() if v is not None}


def max_iterations_from_config(file_config: dict) -> int:
    """`max_iterations` from config.json (or the default), same use as above."""
    value = file_config.get("max_iterations", MAX_ITERATIONS)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 50:
        raise ValueError(
            f"config.json: max_iterations must be an integer from 1 to 50 (got: {value!r})")
    return value


def request_timeout_from_config(file_config: dict) -> int:
    """`request_timeout` from config.json (or the default), in seconds: how long
    to wait for Ollama before giving up. On CPU, several minutes is normal."""
    value = file_config.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(
            f"config.json: request_timeout must be a positive integer (got: {value!r})")
    return value


def num_ctx_from_config(file_config: dict) -> int:
    """`num_ctx` from config.json (or the default), for commands that do not go
    through `get_settings()` (`sensai-schedule`, `sensai-eval`).

    Raises ValueError if the value is not a positive integer: better to stop
    than to send Ollama an absurd window it would silently ignore.
    """
    value = file_config.get("num_ctx", DEFAULT_NUM_CTX)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"config.json: num_ctx must be a positive integer (got: {value!r})")
    return value


def load_system_prompt(path: str) -> str:
    """Load the system prompt from a file (never hardcoded)."""
    resolved = resolve_path(path)
    if resolved is None:
        return ""
    return resolved.read_text(encoding="utf-8").strip()


def prompts_dir() -> Path:
    """Prompt registry folder (A4, ADR-0010): the current directory's one if it
    has one, otherwise the repository's — same rule as `resolve_path`."""
    index = resolve_path(f"prompts/{INDEX_FILE}")
    return index.parent if index else PROJECT_ROOT / "prompts"


def load_prompts(system_path: str | None, memory_path: str | None) -> tuple[str, str, dict]:
    """System and memory prompts, and the versions used (A4, ADR-0010).

    The agent reads the version that carries the registry's bookmark. A file
    given explicitly (`--system-prompt`, `config.json`) takes priority: that is
    how a draft is tried before being registered. Without a registry (branches
    that do not have A4 yet), the old files are read.
    """
    store = PromptStore(prompts_dir())
    texts, versions = {}, {}
    defaults = {"system": DEFAULT_SYSTEM_PROMPT_PATH, "memory": DEFAULT_MEMORY_PROMPT_PATH}
    for name, explicit in (("system", system_path), ("memory", memory_path)):
        if explicit:
            texts[name] = load_system_prompt(explicit)
            versions[name] = f"{Path(explicit).name} (not registered)"
        elif store.exists() and name in store.names():
            texts[name] = store.load(name).strip()
            versions[name] = store.active(name)
        else:
            texts[name] = load_system_prompt(defaults[name])
    return texts["system"], texts["memory"], versions


def get_settings(argv: list[str] | None = None, prog: str | None = None) -> dict:
    """CLI settings: config.json, then the command line.

    `argv`: the arguments to read instead of sys.argv. `sensai-web` (ADR-0035)
    reads its own options first, then passes the rest here to accept the same
    settings as the CLI.
    """
    file_config = load_config_file()

    parser = argparse.ArgumentParser(prog=prog, description="CodeSensai CLI")
    parser.add_argument(
        "--model",
        default=file_config.get("model", DEFAULT_MODEL),
        help="Ollama model name to use",
    )
    parser.add_argument(
        "--host",
        default=file_config.get("host", DEFAULT_HOST),
        help="Ollama API URL",
    )
    parser.add_argument(
        "--system-prompt",
        dest="system_prompt_path",
        # Without an explicit value, the registry's active version (A4, ADR-0010).
        default=file_config.get("system_prompt_path"),
        help="System prompt file to use instead of the active version",
    )
    # Session persistence (feature M1, ADR-0007).
    parser.add_argument(
        "--session",
        default=None,
        help="Id of a session to resume (default: the project's latest)",
    )
    parser.add_argument(
        "--new-session",
        action="store_true",
        help="Start a new session instead of resuming the latest",
    )
    parser.add_argument(
        "--data-dir",
        default=file_config.get("data_dir"),
        help="Folder for sessions and profile (default: $SENSAI_HOME, else ~/.sensai)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=file_config.get("retention_days", DEFAULT_RETENTION_DAYS),
        help="On startup, delete sessions with no message for N days (0: never)",
    )
    # RAG over the project (feature R1, ADR-0009).
    parser.add_argument(
        "--no-rag",
        dest="rag",
        action="store_false",
        default=file_config.get("rag", True),
        help="Do not search the project's files",
    )
    parser.add_argument(
        "--rag-model",
        default=file_config.get("rag_model", DEFAULT_RAG_MODEL),
        help="Ollama embedding model for project search",
    )
    parser.add_argument(
        "--rag-min-score",
        type=float,
        default=file_config.get("rag_min_score", DEFAULT_RAG_MIN_SCORE),
        help="Minimum similarity for a passage to be sent to the model (0 to 1)",
    )
    parser.add_argument(
        "--rag-top-k",
        type=int,
        default=file_config.get("rag_top_k", DEFAULT_RAG_TOP_K),
        help="Maximum number of passages sent to the model per question",
    )
    # Reranking by the chat model (R2, ADR-0032): about 3 s more.
    parser.add_argument(
        "--no-rag-rerank",
        dest="rag_rerank",
        action="store_false",
        default=file_config.get("rag_rerank", True),
        help="Do not have the model rerank the passages found (faster)",
    )
    # Answer cache (A6, ADR-0033): off by default since ADR-0056 (few questions
    # repeat for a solo developer); `--cache` or "cache": true turns it on.
    parser.add_argument(
        "--cache",
        dest="cache",
        action="store_true",
        default=file_config.get("cache", False),
        help="Serve and store cached answers (A6)",
    )
    parser.add_argument(
        "--no-cache",
        dest="cache",
        action="store_false",
        help="Do not serve or store cached answers (default)",
    )
    # Automatic few-shot (A7, ADR-0044): off without an examples file.
    parser.add_argument(
        "--fewshot-examples",
        dest="fewshot_examples",
        default=file_config.get("fewshot_examples"),
        help="JSONL examples file (sensai-eval format) for automatic few-shot",
    )
    parser.add_argument(
        "--fewshot-min-score",
        type=float,
        default=file_config.get("fewshot_min_score", DEFAULT_FEWSHOT_MIN_SCORE),
        help="Minimum similarity for an example to be added to the question (0 to 1)",
    )
    # Context window (M2, ADR-0045): see options.num_ctx in the Ollama API.
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=file_config.get("num_ctx", DEFAULT_NUM_CTX),
        help="Context window sent to Ollama (options.num_ctx)",
    )
    # Generation parameters (ADR-0057): `generation` section of config.json,
    # each key overridable on the command line. Defaults: DEFAULT_GENERATION.
    generation = {**DEFAULT_GENERATION, **(file_config.get("generation") or {})}
    parser.add_argument("--temperature", type=float, default=generation.get("temperature"),
                        help="Generation temperature (0: most predictable)")
    parser.add_argument("--top-p", type=float, default=generation.get("top_p"),
                        help="Nucleus sampling (0 to 1)")
    parser.add_argument("--seed", type=int, default=generation.get("seed"),
                        help="Seed: same answers for equal parameters (reproducible trial runs)")
    parser.add_argument("--num-predict", type=int, default=generation.get("num_predict"),
                        help="Maximum number of tokens generated per answer (-1: unlimited)")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=file_config.get("max_iterations", MAX_ITERATIONS),
        help="Maximum number of model calls per turn (anti-loop guardrail)",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=file_config.get("request_timeout", DEFAULT_REQUEST_TIMEOUT),
        help="Seconds to wait for an Ollama reply (on CPU, several minutes)",
    )
    # Token budget and rolling summary (M2, ADR-0045): on by default, the
    # feature catalog asks for automatic triggering when nearing the limit.
    parser.add_argument(
        "--no-token-budget",
        dest="token_budget",
        action="store_false",
        default=file_config.get("token_budget", True),
        help="Send the full history to the model, without summarizing old turns",
    )
    parser.add_argument(
        "--token-budget-max",
        type=int,
        # No default here: argparse evaluates a default BEFORE reading argv, so
        # a default derived from num_ctx would ignore a `--num-ctx` passed on the
        # command line (PR #97 review). It is derived below, once num_ctx is known.
        default=file_config.get("token_budget_max"),
        help="Tokens (estimated) beyond which old turns are summarized "
             "(default: num_ctx minus a margin for the answer)",
    )
    parser.add_argument(
        "--token-budget-keep-recent",
        type=int,
        default=file_config.get("token_budget_keep_recent", DEFAULT_TOKEN_BUDGET_KEEP_RECENT),
        help="Number of recent turns always kept intact, never summarized",
    )
    args = parser.parse_args(argv)
    if args.retention_days < 0:
        # A negative duration would purge every session: refuse instead of guessing.
        parser.error("--retention-days must be zero or positive (0: never purge)")
    if not 0 <= args.rag_min_score <= 1:
        parser.error("--rag-min-score must be between 0 and 1")
    if args.rag_top_k < 1:
        parser.error("--rag-top-k must be at least 1")
    if not 0 <= args.fewshot_min_score <= 1:
        parser.error("--fewshot-min-score must be between 0 and 1")
    if args.num_ctx < 1:
        parser.error("--num-ctx must be at least 1")
    unknown = set(file_config.get("generation") or {}) - set(GENERATION_KEYS)
    if unknown:
        # Like tools/files: a misspelled parameter must not pass for an active one.
        names = ", ".join(sorted(unknown))
        parser.error(f"config.json: unknown generation parameter: {names} "
                     f"(accepted: {', '.join(GENERATION_KEYS)})")
    if args.temperature is not None and not 0 <= args.temperature <= 2:
        parser.error("--temperature must be between 0 and 2")
    if args.top_p is not None and not 0 < args.top_p <= 1:
        parser.error("--top-p must be between 0 (exclusive) and 1")
    if args.num_predict is not None and args.num_predict == 0:
        parser.error("--num-predict must be positive, or -1 for no limit")
    if not 1 <= args.max_iterations <= 50:
        parser.error("--max-iterations must be between 1 and 50")
    # Same check as the other commands: `true` or "600" in config.json
    # must not pass for a valid timeout.
    try:
        request_timeout_from_config(file_config)
    except ValueError as e:
        parser.error(str(e))
    if args.request_timeout < 1:
        parser.error("--request-timeout must be at least 1")
    if args.token_budget_max is None:
        args.token_budget_max = budget_from_num_ctx(args.num_ctx)
    if args.token_budget_max < 1:
        parser.error("--token-budget-max must be at least 1")
    if args.token_budget_max >= args.num_ctx:
        # A budget at least as large as the window protects nothing: Ollama
        # would truncate before the summary kicks in.
        parser.error(
            f"--token-budget-max ({args.token_budget_max}) must stay below --num-ctx "
            f"({args.num_ctx}), leaving room for the answer"
        )
    if args.token_budget_keep_recent < 2:
        # Below 2: nothing kept whole survives the cut (see compress_messages,
        # which requires at least one pair on each side).
        parser.error("--token-budget-keep-recent must be at least 2")
    # `tools` sections (gateway preferences, docs/architecture/tool-contract.md) and
    # `files` (allowed folders, ADR-0011). An unknown key stops the CLI:
    # a misspelled restriction must not pass for an active one.
    try:
        tool_preferences = ToolPreferences.from_dict(file_config.get("tools") or {})
        file_permissions = FilePermissions.from_dict(file_config.get("files"))
        # MCP servers (T1, ADR-0041): checked here, launched by the CLI or the web app.
        mcp_servers = parse_mcp_config(file_config.get("mcp_servers"))
    except (ValueError, TypeError) as e:
        parser.error(f"config.json: {e}")
    # Personas (A5, ADR-0042): an unknown default persona or an incomplete
    # profile stops the CLI, as for tools/files above.
    try:
        personas = PersonaStore.from_config(file_config.get("personas"))
    except PersonaError as e:
        parser.error(f"config.json: {e}")

    system_prompt, memory_prompt, prompt_versions = load_prompts(
        args.system_prompt_path, file_config.get("memory_prompt_path")
    )
    return {
        "model": args.model,
        "host": args.host,
        "system_prompt": system_prompt,
        "memory_prompt": memory_prompt,
        "prompt_versions": prompt_versions,
        "session": args.session,
        "new_session": args.new_session,
        "data_dir": args.data_dir,
        "retention_days": args.retention_days,
        "rag": args.rag,
        "rag_model": args.rag_model,
        "rag_min_score": args.rag_min_score,
        "rag_top_k": args.rag_top_k,
        "rag_rerank": args.rag_rerank,
        "cache": args.cache,
        "fewshot_examples": args.fewshot_examples,
        "fewshot_min_score": args.fewshot_min_score,
        "num_ctx": args.num_ctx,
        "generation": {k: v for k, v in {
            **generation, "temperature": args.temperature, "top_p": args.top_p,
            "seed": args.seed, "num_predict": args.num_predict,
        }.items() if v is not None},
        "max_iterations": args.max_iterations,
        "request_timeout": args.request_timeout,
        "token_budget": args.token_budget,
        "token_budget_max": args.token_budget_max,
        "token_budget_keep_recent": args.token_budget_keep_recent,
        "tool_preferences": tool_preferences,
        "file_permissions": file_permissions,
        "mcp_servers": mcp_servers,
        # User-added refusal rules (EV2, ADR-0027): validated at startup by
        # InputRules.from_config, not here.
        "input_blocklist": file_config.get("input_blocklist"),
        # Public share links (X3): off by default (ADR-0056).
        "share_links": file_config.get("share_links", False) is True,
        # Personas (A5, ADR-0042).
        "personas": personas,
    }
