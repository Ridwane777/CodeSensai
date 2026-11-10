"""
CLI terminal display: welcome screen, input area, tool calls, diffs,
confirmations, Markdown answer, interruption with Esc.

Only display lives here. The CLI (cli.py) keeps the logic: it receives the
agent's events (core/events.py) and hands them to `TurnView`, just as the web
serializes them to JSON (ADR-0005).

Two modes:
- **interactive terminal**: colors, spinner with elapsed time, answer rendered
  as Markdown while it streams, prompt with history and completion, arrow-key
  confirmation menu, Esc to interrupt a turn;
- **otherwise** (redirected input, tests, CI): plain text and `input()`, which
  tests replace. This must remain the mode used under pytest.
"""
from __future__ import annotations

import re
import select
import sys
import threading
import time
from pathlib import Path

from rich.console import Console, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from sensai.core.events import Done, Error, Event, Thought, Token, ToolCall, ToolReturn

# soft_wrap: Rich does not wrap long lines itself (the terminal does);
# without it, a path or a diff would be cut in the middle in text mode.
console = Console(highlight=False, soft_wrap=True)

ACCENT = "#d97757"
COMMANDS = (
    "/help", "/profile", "/remember", "/forget", "/sessions", "/state", "/facts",
    "/cache", "/again", "/context", "/schedule", "/eval", "exit",
)
# Label shown for each tool, and the argument shown in parentheses.
TOOL_LABELS = {
    "read_file": ("Read", "path"),
    "write_file": ("Write", "path"),
    "run_code": ("Run", None),
    "web_search": ("Web search", "query"),
    "search_codebase": ("Project search", "query"),
    "update_state": ("State document", "section"),
    "save_fact": ("Memory", "entity"),
    "recall_facts": ("Memory", "entity"),
}


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def plain(text: str, style: str | None = None) -> None:
    """Variable text (command output, path…): never interpreted as Rich
    markup, otherwise "[Blocked]" would disappear."""
    console.print(Text(text, style=style or ""))


def info(text: str) -> None:
    plain(text, "dim")


def warn(text: str) -> None:
    plain(text, "yellow")


def error(text: str) -> None:
    plain(text, "bold red")


# --- Welcome -----------------------------------------------------------------------


def banner(lines: list[tuple[str, str]], notes: list[str]) -> None:
    """The welcome panel: the title, then one line per item."""
    body = Text()
    body.append("✻ ", style=ACCENT)
    body.append("Welcome to ", style="bold")
    body.append("CodeSensai", style=f"bold {ACCENT}")
    body.append(" !\n\n", style="bold")
    body.append("  /help for help, exit to quit\n\n", style="dim italic")
    width = max((len(label) for label, _ in lines), default=0)
    for label, value in lines:
        body.append(f"  {label.ljust(width)} : ", style="dim")
        body.append(f"{value}\n")
    body.rstrip()
    console.print(Panel(body, border_style=ACCENT, expand=False, padding=(0, 1)))
    for note in notes:
        warn(note)


HELP = """\
Chat commands (nothing is sent to the model):
  /remember <text>           add a preference to the profile (/profile, /forget)
  /sessions                  sessions of this project
  /state                     SENSAI.md state document
  /state history | undo <s>  its changes, undo the last one of a section
  /facts [entity]            fact memory
  /facts forget | history    delete a fact, show an entity's history
  /persona [list|use <id>]   active persona, list personas, switch persona
  /cache [clear]             cached answers: summary, or clear everything
  /again                     ask the model the last question again
  /context                   the exact prompt sent to the model and its settings
  /schedule …  /eval …       scheduled tasks, evaluation
  /structured <schema.json> <request>   JSON answer matching a schema
  exit                       quit

Shortcuts: ↑ ↓ history · Tab completes a command · Esc interrupts the agent
· Ctrl+C twice to quit"""


def loading(text: str):
    """Spinner while waiting without events (model loading)."""
    return console.status(Text(text, style=ACCENT), spinner="dots")


# --- Input area ---------------------------------------------------------------------


class Prompt:
    """The `>` input area under a rule, with a help line below it.
    In a terminal: persistent history, command completion, Ctrl+C twice to
    quit; otherwise `input()`, which tests replace."""

    def __init__(self, history_file: Path | None = None) -> None:
        self._session = None
        self._last_interrupt = 0.0
        if interactive():
            from prompt_toolkit import PromptSession
            from prompt_toolkit.completion import WordCompleter
            from prompt_toolkit.history import FileHistory, InMemoryHistory

            history = InMemoryHistory()
            if history_file is not None:
                try:
                    history_file.parent.mkdir(parents=True, exist_ok=True)
                    history = FileHistory(str(history_file))
                except OSError:
                    pass
            self._session = PromptSession(
                history=history,
                completer=WordCompleter(list(COMMANDS), sentence=True),
                complete_while_typing=True,
            )

    def read(self) -> str:
        if self._session is None:
            return input("> ")
        from prompt_toolkit.formatted_text import HTML

        console.print()
        console.print(Rule(style="dim"))
        try:
            line = self._session.prompt(
                HTML(f'<style fg="{ACCENT}"><b>&gt;</b></style> '),
                bottom_toolbar=HTML(
                    "<i>  /help for commands · ↑ history · "
                    "Esc during an answer to interrupt it</i>"
                ),
            )
        except KeyboardInterrupt:
            now = time.monotonic()
            if now - self._last_interrupt < 2:
                raise
            self._last_interrupt = now
            info("  Press Ctrl+C again to quit.")
            return ""
        return line


# --- Diffs -----------------------------------------------------------------------------

_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def diff_view(summary: str) -> RenderableType:
    """A unified diff with line numbers and colored background; other text
    as is. The `---`/`+++` headers are hidden."""
    lines = summary.splitlines()
    if not any(_HUNK.match(line) for line in lines):
        return _colored(summary)
    table = Table.grid(padding=(0, 1))
    table.add_column(justify="right", style="dim", no_wrap=True)
    table.add_column()
    old = new = 0
    for line in lines:
        hunk = _HUNK.match(line)
        if hunk:
            old, new = int(hunk.group(1)), int(hunk.group(2))
            table.add_row("", Text("⋮", style="dim"))
        elif line.startswith(("+++", "---")):
            continue
        elif line.startswith("+"):
            table.add_row(str(new), Text(line, style="on #1f3d27"))
            new += 1
        elif line.startswith("-"):
            table.add_row(str(old), Text(line, style="on #4a2124"))
            old += 1
        elif line.startswith(" "):
            table.add_row(str(new), Text(line))
            old += 1
            new += 1
        else:
            table.add_row("", Text(line, style="bold"))
    return table


def _colored(summary: str) -> Text:
    text = Text()
    for line in summary.splitlines():
        style = "green" if line.startswith("+") else "red" if line.startswith("-") else ""
        text.append(line + "\n", style=style)
    text.rstrip()
    return text


# --- Confirmation -----------------------------------------------------------------------

_pending_instruction: str | None = None
_watcher: EscWatcher | None = None


def take_instruction() -> str | None:
    """The instruction given with "No, and tell it what to do", returned once."""
    global _pending_instruction
    instruction, _pending_instruction = _pending_instruction, None
    return instruction


def confirm(title: str, details: str) -> bool:
    """Permission request: the plan in a panel, then a choice. Only an explicit
    "yes" authorizes; "No, and tell it what to do" keeps the instruction to
    send it to the agent at the end of the turn."""
    global _pending_instruction
    console.print()
    console.print(Panel(diff_view(details), title=title, title_align="left",
                        border_style="yellow", expand=False, padding=(0, 1)))
    if not interactive():
        try:
            answer = input("Allow? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return False
        return answer in ("y", "o", "yes", "oui")

    from prompt_toolkit import prompt as ask
    from prompt_toolkit.shortcuts import choice

    if _watcher is not None:
        _watcher.pause()
    try:
        answer = choice(
            "Allow this action?",
            options=[("yes", "Yes"), ("tell", "No, and tell the agent what to do"),
                     ("no", "No")],
            default="yes",
        )
        if answer == "tell":
            text = ask("  ⎿ What should the agent do? ").strip()
            _pending_instruction = text or None
        return answer == "yes"
    except (EOFError, KeyboardInterrupt):
        return False
    finally:
        if _watcher is not None:
            _watcher.resume()


# --- Esc to interrupt --------------------------------------------------------------------


class EscWatcher:
    """Listens for the Esc key during a turn (terminal in cbreak mode).

    Paused during a confirmation so it does not steal its keystrokes.
    """

    def __init__(self) -> None:
        self.pressed = threading.Event()
        self._paused = threading.Event()
        self._stop = threading.Event()
        self._saved = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> EscWatcher:
        global _watcher
        try:
            import termios
            import tty

            self._saved = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except (ImportError, OSError, ValueError):
            return self
        _watcher = self
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        return self

    def _listen(self) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if ready and not self._paused.is_set() and sys.stdin.read(1) == "\x1b":
                self.pressed.set()

    def pause(self) -> None:
        self._paused.set()
        self._restore()

    def resume(self) -> None:
        self._paused.clear()
        try:
            import tty

            tty.setcbreak(sys.stdin.fileno())
        except (ImportError, OSError, ValueError):
            pass

    def _restore(self) -> None:
        if self._saved is not None:
            import termios

            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._saved)

    def __exit__(self, *exc: object) -> None:
        global _watcher
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        self._restore()
        _watcher = None


# --- One agent turn ----------------------------------------------------------------------


class _Thinking:
    """"✻ Thinking… (12 s · Esc to interrupt)", recomputed on every frame."""

    def __init__(self) -> None:
        self.start = time.monotonic()
        self.spinner = Spinner("dots", style=ACCENT)

    def __rich_console__(self, console, options):
        seconds = int(time.monotonic() - self.start)
        self.spinner.text = Text.assemble(
            ("Thinking…", ACCENT), (f" ({seconds} s · Esc to interrupt)", "dim"))
        yield self.spinner


def tool_label(event: ToolCall) -> Text:
    label, key = TOOL_LABELS.get(event.name, (event.name, None))
    args = event.arguments or {}
    shown = str(args.get(key, "")) if key else ""
    if not shown and event.name == "run_code" and str(args.get("code", "")).strip():
        shown = str(args["code"]).strip().splitlines()[0]
    shown = shown.splitlines()[0] if shown else ""
    text = Text(label, style="bold")
    if shown:
        text.append(f"({shown[:60]}{'…' if len(shown) > 60 else ''})")
    return text


def tool_summary(name: str, ok: bool, content: str) -> str:
    """One useful line about what the tool did, rather than its first word."""
    body = content.strip()
    lines = [line for line in body.splitlines() if line.strip()]
    first = lines[0] if lines else "(empty)"
    if not ok:
        return first[:120]
    if name == "read_file":
        return f"{len(body.splitlines())} lines read"
    if name == "write_file":
        return "File created" if first.startswith("Created") else "File modified"
    if name == "web_search":
        count = sum(1 for line in lines if re.match(r"\s*\d+\.", line))
        return f"{count} result(s)"
    if name == "search_codebase":
        found = re.search(r"(\d+) passage", first)
        return f"{found.group(1)} passage(s) found" if found else first[:120]
    if name == "recall_facts":
        count = sum(1 for line in lines if line.startswith("- "))
        return f"{count} fact(s) found" if count else first[:120]
    if name == "run_code":
        return first[:120] + (f"  (+{len(lines) - 1} lines)" if len(lines) > 1 else "")
    return first[:120]


_CALL_TEXT = re.compile(r"<function=|<tool_call>")


def visible_answer(answer: str) -> str:
    """The part of the answer to show: nothing from a tool call written as text
    onward (the agent parses or retries it, ADR-0031; no need to display it)."""
    found = _CALL_TEXT.search(answer)
    return answer[:found.start()].rstrip() if found else answer


def _bulleted(body: RenderableType, bullet: str = "●", style: str = "") -> Table:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=1)
    grid.add_column()
    grid.add_row(Text(bullet, style=style), body)
    return grid


def cached_answer(answer: str, question: str, created_at, similarity: float) -> None:
    """Answer served from the cache (A6): say where it comes from so the user
    can judge whether it still holds (US-A6-3)."""
    when = created_at.astimezone().strftime("%d/%m at %H:%M")
    header = Text("↺ from cache · question \"", style="dim")
    header.append(question, style="dim italic")
    header.append(f"\" from {when} (similarity {similarity:.2f}) · /again to ask again",
                  style="dim")
    if not interactive():
        console.print(header)
        console.print(answer, markup=False)
        return
    console.print()
    console.print(_bulleted(header, bullet="↺", style=ACCENT))
    console.print(_bulleted(Markdown(answer)))


class TurnView:
    """Displays a turn's events. In a terminal: spinner with elapsed time until
    the first event, calls as ●, results as ⎿, answer streamed as Markdown."""

    def __init__(self) -> None:
        self.live = interactive()
        self._answer = ""
        self._markdown: Live | None = None
        self._thinking: Live | None = None
        if self.live:
            console.print()
            self._start_thinking()

    def _start_thinking(self) -> None:
        if self.live and self._thinking is None:
            self._thinking = Live(_Thinking(), console=console, refresh_per_second=10,
                                  transient=True)
            self._thinking.start()

    def _stop_thinking(self) -> None:
        if self._thinking is not None:
            self._thinking.stop()
            self._thinking = None

    def _end_answer(self) -> None:
        if self._markdown is not None:
            self._markdown.stop()
            self._markdown = None
        self._answer = ""

    def show(self, event: Event) -> None:
        self._stop_thinking()
        if isinstance(event, Token):
            self._answer += event.text
            if not self.live:
                console.print(event.text, end="", markup=False)
                return
            shown = visible_answer(self._answer)
            if not shown.strip():
                return
            if self._markdown is None:
                self._markdown = Live(console=console, refresh_per_second=12,
                                      vertical_overflow="visible")
                self._markdown.start()
            self._markdown.update(_bulleted(Markdown(shown)))
            return
        self._end_answer()
        if isinstance(event, Thought):
            plain(f"✻ {event.text}", "dim italic")
        elif isinstance(event, ToolCall):
            console.print(_bulleted(tool_label(event), style=ACCENT))
        elif isinstance(event, ToolReturn):
            line = Text("  ⎿  ", style="dim")
            line.append(tool_summary(event.name, event.ok, event.content),
                        style="" if event.ok else "red")
            console.print(line)
            # After a tool call, the model thinks again.
            self._start_thinking()
        elif isinstance(event, Error):
            error(f"✗ [Error] {event.message}")
        elif isinstance(event, Done) and event.reason == "max_iterations":
            warn("[Stopped] Maximum number of steps reached without a final answer.")

    def interrupted(self) -> None:
        self._stop_thinking()
        self._end_answer()
        plain("  ⎿  Interrupted by the user.", "yellow")

    def close(self) -> None:
        self._stop_thinking()
        self._end_answer()
        if not self.live:
            console.print()
