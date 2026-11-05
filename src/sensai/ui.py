"""
Affichage du CLI dans le terminal : accueil, zone de saisie, appels d'outils,
diffs, confirmations, réponse en Markdown, interruption par Échap.

Seul l'affichage vit ici. Le CLI (cli.py) garde la logique : il reçoit les
événements de l'agent (core/events.py) et les confie à `TurnView`, comme le
web les sérialisera en JSON (ADR-0005).

Deux modes :
- **terminal interactif** : couleurs, animation avec le temps écoulé, réponse
  rendue en Markdown au fil de l'eau, invite avec historique et complétion,
  menu de confirmation aux flèches, Échap pour interrompre un tour ;
- **sinon** (entrée redirigée, tests, CI) : texte brut et `input()`, que les
  tests remplacent. Ce mode doit rester celui de pytest.
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

# soft_wrap : Rich ne coupe pas les lignes longues lui-même (le terminal le
# fait) ; sans lui, un chemin ou un diff serait coupé au milieu en mode texte.
console = Console(highlight=False, soft_wrap=True)

ACCENT = "#d97757"
COMMANDS = (
    "/help", "/profile", "/remember", "/forget", "/sessions", "/state", "/facts",
    "/cache", "/again", "/context", "/schedule", "/eval", "exit",
)
# Libellé affiché pour chaque outil, et l'argument montré entre parenthèses.
TOOL_LABELS = {
    "read_file": ("Lecture", "path"),
    "write_file": ("Écriture", "path"),
    "run_code": ("Exécution", None),
    "web_search": ("Recherche web", "query"),
    "search_codebase": ("Recherche projet", "query"),
    "update_state": ("Document d'état", "section"),
    "save_fact": ("Mémoire", "entity"),
    "recall_facts": ("Mémoire", "entity"),
}


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def plain(text: str, style: str | None = None) -> None:
    """Texte variable (sortie de commande, chemin…) : jamais interprété comme
    une balise Rich, sinon « [Bloqué] » disparaîtrait."""
    console.print(Text(text, style=style or ""))


def info(text: str) -> None:
    plain(text, "dim")


def warn(text: str) -> None:
    plain(text, "yellow")


def error(text: str) -> None:
    plain(text, "bold red")


# --- Accueil ---------------------------------------------------------------------


def banner(lines: list[tuple[str, str]], notes: list[str]) -> None:
    """Le cadre de bienvenue : le titre, puis une ligne par information."""
    body = Text()
    body.append("✻ ", style=ACCENT)
    body.append("Bienvenue dans ", style="bold")
    body.append("CodeSensei", style=f"bold {ACCENT}")
    body.append(" !\n\n", style="bold")
    body.append("  /help pour l'aide, exit pour quitter\n\n", style="dim italic")
    width = max((len(label) for label, _ in lines), default=0)
    for label, value in lines:
        body.append(f"  {label.ljust(width)} : ", style="dim")
        body.append(f"{value}\n")
    body.rstrip()
    console.print(Panel(body, border_style=ACCENT, expand=False, padding=(0, 1)))
    for note in notes:
        warn(note)


HELP = """\
Commandes du chat (rien n'est envoyé au modèle) :
  /remember <texte>          ajouter une préférence au profil (/profile, /forget)
  /sessions                  sessions de ce projet
  /state                     document d'état SENSAI.md
  /state history | undo <s>  ses modifications, annuler la dernière d'une section
  /facts [entité]            mémoire de faits
  /facts forget | history    effacer un fait, voir l'historique d'une entité
  /persona [list|use <id>]   persona active, liste des personas, en changer
  /cache [clear]             réponses en cache : bilan, ou tout vider
  /again                     redemander au modèle la dernière question
  /context                   le prompt exact envoyé au modèle et ses réglages
  /schedule …  /eval …       tâches planifiées, évaluation
  /structured <schéma.json> <demande>   réponse JSON conforme à un schéma
  exit                       quitter

Raccourcis : ↑ ↓ historique · Tab complète une commande · Échap interrompt l'agent
· Ctrl+C deux fois pour quitter"""


def loading(text: str):
    """Animation pendant une attente sans événement (chargement du modèle)."""
    return console.status(Text(text, style=ACCENT), spinner="dots")


# --- Zone de saisie ------------------------------------------------------------------


class Prompt:
    """La zone de saisie `>` sous un trait, avec une ligne d'aide dessous.
    En terminal : historique persistant, complétion des commandes, Ctrl+C deux
    fois pour quitter ; sinon `input()`, que les tests remplacent."""

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
                    "<i>  /help pour les commandes · ↑ historique · "
                    "Échap pendant une réponse pour l'interrompre</i>"
                ),
            )
        except KeyboardInterrupt:
            now = time.monotonic()
            if now - self._last_interrupt < 2:
                raise
            self._last_interrupt = now
            info("  Appuie encore sur Ctrl+C pour quitter.")
            return ""
        return line


# --- Diffs -----------------------------------------------------------------------------

_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def diff_view(summary: str) -> RenderableType:
    """Un diff unifié avec numéros de ligne et fond coloré ; le reste du texte
    tel quel. Les en-têtes `---`/`+++` sont masqués."""
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
    """La consigne donnée avec « Non, et dire quoi faire », une seule fois."""
    global _pending_instruction
    instruction, _pending_instruction = _pending_instruction, None
    return instruction


def confirm(title: str, details: str) -> bool:
    """Demande d'autorisation : le plan dans un cadre, puis un choix. Seul un
    « oui » explicite autorise ; « Non, et dire quoi faire » garde la consigne
    pour l'envoyer à l'agent à la fin du tour."""
    global _pending_instruction
    console.print()
    console.print(Panel(diff_view(details), title=title, title_align="left",
                        border_style="yellow", expand=False, padding=(0, 1)))
    if not interactive():
        try:
            answer = input("Autoriser ? [y/N] ").strip().lower()
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
            "Autoriser cette action ?",
            options=[("yes", "Oui"), ("tell", "Non, et dire à l'agent quoi faire"),
                     ("no", "Non")],
            default="yes",
        )
        if answer == "tell":
            text = ask("  ⎿ Que doit faire l'agent ? ").strip()
            _pending_instruction = text or None
        return answer == "yes"
    except (EOFError, KeyboardInterrupt):
        return False
    finally:
        if _watcher is not None:
            _watcher.resume()


# --- Échap pour interrompre ---------------------------------------------------------------


class EscWatcher:
    """Écoute la touche Échap pendant un tour (terminal en mode caractère).

    Mis en pause pendant une confirmation, pour ne pas lui voler les touches.
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


# --- Un tour de l'agent ------------------------------------------------------------------


class _Thinking:
    """« ✻ Réflexion… (12 s · Échap pour interrompre) », recalculé à chaque image."""

    def __init__(self) -> None:
        self.start = time.monotonic()
        self.spinner = Spinner("dots", style=ACCENT)

    def __rich_console__(self, console, options):
        seconds = int(time.monotonic() - self.start)
        self.spinner.text = Text.assemble(
            ("Réflexion…", ACCENT), (f" ({seconds} s · Échap pour interrompre)", "dim"))
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
    """Une ligne utile sur ce qu'a fait l'outil, plutôt que son premier mot."""
    body = content.strip()
    lines = [line for line in body.splitlines() if line.strip()]
    first = lines[0] if lines else "(vide)"
    if not ok:
        return first[:120]
    if name == "read_file":
        return f"{len(body.splitlines())} lignes lues"
    if name == "write_file":
        return "Fichier créé" if first.startswith("Created") else "Fichier modifié"
    if name == "web_search":
        count = sum(1 for line in lines if re.match(r"\s*\d+\.", line))
        return f"{count} résultat(s)"
    if name == "search_codebase":
        found = re.search(r"(\d+) passage", first)
        return f"{found.group(1)} passage(s) trouvé(s)" if found else first[:120]
    if name == "recall_facts":
        count = sum(1 for line in lines if line.startswith("- "))
        return f"{count} fait(s) trouvé(s)" if count else first[:120]
    if name == "run_code":
        return first[:120] + (f"  (+{len(lines) - 1} lignes)" if len(lines) > 1 else "")
    return first[:120]


_CALL_TEXT = re.compile(r"<function=|<tool_call>")


def visible_answer(answer: str) -> str:
    """Ce qu'on montre de la réponse : rien à partir d'un appel d'outil écrit
    en texte (l'agent le lit ou le relance, ADR-0031 ; inutile de l'afficher)."""
    found = _CALL_TEXT.search(answer)
    return answer[:found.start()].rstrip() if found else answer


def _bulleted(body: RenderableType, bullet: str = "●", style: str = "") -> Table:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=1)
    grid.add_column()
    grid.add_row(Text(bullet, style=style), body)
    return grid


def cached_answer(answer: str, question: str, created_at, similarity: float) -> None:
    """Réponse servie par le cache (A6) : on dit d'où elle vient pour qu'on
    puisse juger si elle vaut encore (US-A6-3)."""
    when = created_at.astimezone().strftime("%d/%m à %H:%M")
    header = Text("↺ depuis le cache · question « ", style="dim")
    header.append(question, style="dim italic")
    header.append(f" » du {when} (similarité {similarity:.2f}) · /again pour redemander",
                  style="dim")
    if not interactive():
        console.print(header)
        console.print(answer, markup=False)
        return
    console.print()
    console.print(_bulleted(header, bullet="↺", style=ACCENT))
    console.print(_bulleted(Markdown(answer)))


class TurnView:
    """Affiche les événements d'un tour. En terminal : animation avec le temps
    écoulé jusqu'au premier événement, appels en ●, résultats en ⎿, réponse en
    Markdown au fil de l'eau."""

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
            # Après un appel d'outil, le modèle réfléchit de nouveau.
            self._start_thinking()
        elif isinstance(event, Error):
            error(f"✗ [Erreur] {event.message}")
        elif isinstance(event, Done) and event.reason == "max_iterations":
            warn("[Arrêt] Nombre maximal d'étapes atteint sans réponse finale.")

    def interrupted(self) -> None:
        self._stop_thinking()
        self._end_answer()
        plain("  ⎿  Interrompu par l'utilisateur.", "yellow")

    def close(self) -> None:
        self._stop_thinking()
        self._end_answer()
        if not self.live:
            console.print()
