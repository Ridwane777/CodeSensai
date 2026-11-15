"""
[Workstream D - Christopher] Turn log [EV3]: what the agent did, measured on the
server side and kept across sessions (ADR-0053).

A SQLite file `<data_dir>/journal.db` (600, directory 700, like sessions):

- one row per TURN: session, project, start date (ISO, UTC), time spent
  waiting for the model (ms), estimated tokens sent, outcome, interface (web/cli);
- one row per TOOL CALL: tool, arguments (filtered by the EV2 guardrails
  then truncated), duration (ms), success, agent ("main" or the subagent's
  role).

Durations are wall-clock (time.monotonic): a tool's includes waiting for the
user's confirmation; the "model" time is the turn's duration minus that of
the main agent's tools.

Rule: the log never breaks a turn. `TurnRecorder` catches every error and
logs it as a warning.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sensai.core.events import Done, Event, ToolCall, ToolReturn
from sensai.execution.guardrails import filter_output
from sensai.knowledge.memory import ensure_private_dir, restrict_file

log = logging.getLogger(__name__)

JOURNAL_FILE = "journal.db"
# Enough to recognize the call; a whole file passed as an argument does not belong here.
MAX_ARGUMENT_CHARS = 500
MAIN_AGENT = "main"

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    project     TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    model_ms    INTEGER,
    tokens_sent INTEGER,
    outcome     TEXT NOT NULL,
    interface   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id, started_at);
CREATE INDEX IF NOT EXISTS turns_started ON turns(started_at);
CREATE TABLE IF NOT EXISTS tool_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id     INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    tool        TEXT NOT NULL,
    arguments   TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    ok          INTEGER NOT NULL,
    agent       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tool_calls_turn ON tool_calls(turn_id);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def safe_arguments(arguments: Any) -> str:
    """The arguments as we keep them: JSON, secrets masked (EV2), truncated."""
    try:
        text = json.dumps(arguments, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError):
        text = str(arguments)
    text = filter_output(text)
    if len(text) > MAX_ARGUMENT_CHARS:
        text = text[:MAX_ARGUMENT_CHARS] + "…"
    return text


@dataclass
class ToolRecord:
    tool: str
    arguments: str
    duration_ms: int
    ok: bool
    agent: str = MAIN_AGENT


@dataclass
class TurnRecord:
    session_id: str | None
    project: str
    started_at: str
    model_ms: int | None
    tokens_sent: int | None
    outcome: str
    interface: str
    tools: list[ToolRecord] = field(default_factory=list)


class Journal:
    """The storage. One connection per operation (the web server calls from
    several threads), like `SessionStore`."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        ensure_private_dir(self.db_path.parent)
        is_new = not self.db_path.exists()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
        if is_new:
            # Arguments quote project paths and queries: owner only.
            restrict_file(self.db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def write(self, turn: TurnRecord) -> int:
        """Writes a turn and its tool calls in one transaction; returns the turn id."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO turns (session_id, project, started_at, model_ms, tokens_sent,"
                " outcome, interface) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (turn.session_id, turn.project, turn.started_at, turn.model_ms,
                 turn.tokens_sent, turn.outcome, turn.interface),
            )
            turn_id = int(cur.lastrowid or 0)
            conn.executemany(
                "INSERT INTO tool_calls (turn_id, position, tool, arguments, duration_ms, ok,"
                " agent) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(turn_id, i, t.tool, t.arguments, t.duration_ms, int(t.ok), t.agent)
                 for i, t in enumerate(turn.tools)],
            )
        return turn_id

    def turns(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """A session's turns, newest first, each with its tools."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY started_at DESC, id DESC"
                " LIMIT ?", (session_id, limit)).fetchall()
            out = []
            for row in rows:
                tools = conn.execute(
                    "SELECT tool, arguments, duration_ms, ok, agent FROM tool_calls"
                    " WHERE turn_id = ? ORDER BY position", (row["id"],)).fetchall()
                out.append({
                    "id": row["id"], "session_id": row["session_id"],
                    "started_at": row["started_at"], "model_ms": row["model_ms"],
                    "tokens_sent": row["tokens_sent"], "outcome": row["outcome"],
                    "interface": row["interface"],
                    "tools": [{"tool": t["tool"], "arguments": t["arguments"],
                               "duration_ms": t["duration_ms"], "ok": bool(t["ok"]),
                               "agent": t["agent"]} for t in tools],
                })
        return out

    def metrics(self, days: int = 7) -> dict[str, Any]:
        """Per tool: calls, failures, mean and max duration; and the model time.
        Over turns started in the last `days` days, all sessions and interfaces."""
        since = (_now() - timedelta(days=max(days, 0))).isoformat()
        with self._connect() as conn:
            tools = conn.execute(
                "SELECT c.tool, COUNT(*) AS calls, SUM(1 - c.ok) AS failures,"
                " AVG(c.duration_ms) AS mean_ms, MAX(c.duration_ms) AS max_ms"
                " FROM tool_calls c JOIN turns t ON t.id = c.turn_id"
                " WHERE t.started_at >= ? GROUP BY c.tool ORDER BY calls DESC, c.tool",
                (since,)).fetchall()
            model = conn.execute(
                "SELECT COUNT(*) AS turns, AVG(model_ms) AS mean_ms, MAX(model_ms) AS max_ms,"
                " SUM(outcome != 'final_answer') AS not_final"
                " FROM turns WHERE started_at >= ?", (since,)).fetchone()
        return {
            "days": days,
            "tools": [{"tool": r["tool"], "calls": r["calls"], "failures": r["failures"] or 0,
                       "mean_ms": round(r["mean_ms"] or 0), "max_ms": r["max_ms"] or 0}
                      for r in tools],
            "model": {"turns": model["turns"] or 0,
                      "mean_ms": round(model["mean_ms"]) if model["mean_ms"] is not None else None,
                      "max_ms": model["max_ms"],
                      "not_final": model["not_final"] or 0},
        }

    def purge(self, retention_days: int) -> int:
        """Deletes turns older than `retention_days` (0: never), like sessions.
        Returns the number of turns deleted (their tools go with them)."""
        if retention_days <= 0:
            return 0
        cutoff = (_now() - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn:
            return conn.execute("DELETE FROM turns WHERE started_at < ?", (cutoff,)).rowcount

    def delete_session(self, session_id: str) -> int:
        """Deletes the log of a deleted conversation, then VACUUM (like sessions:
        otherwise the argument text would remain in the file's free pages)."""
        with self._connect() as conn:
            deleted = conn.execute("DELETE FROM turns WHERE session_id = ?",
                                   (session_id,)).rowcount
        if deleted:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("VACUUM")
            finally:
                conn.close()
        return deleted


def open_journal(data_dir: Path) -> Journal | None:
    """Opens the log; None (with a warning) if it cannot be opened."""
    try:
        return Journal(data_dir / JOURNAL_FILE)
    except (sqlite3.Error, OSError) as e:
        log.warning("EV3 log disabled: %s", e)
        return None


class TurnRecorder:
    """Measures a turn from its events and writes it at the end.

    `on_event` receives every event of the agent loop; `subagent_call` every
    tool run by a subagent (already timed); `finish` writes.
    No method raises: a log failure becomes a warning.
    """

    def __init__(self, journal: Journal | None, *, session_id: str | None, project: str,
                 interface: str, tokens_sent: int | None = None,
                 clock=time.monotonic) -> None:
        self.journal = journal
        self.clock = clock
        self.record = TurnRecord(session_id=session_id, project=project,
                                 started_at=_now().isoformat(), model_ms=None,
                                 tokens_sent=tokens_sent, outcome="error", interface=interface)
        self._t0 = clock()
        self._open: dict[str, tuple[float, str, Any]] = {}
        self._tool_s = 0.0
        self._done = False

    def on_event(self, event: Event) -> None:
        try:
            if isinstance(event, ToolCall):
                self._open[event.id] = (self.clock(), event.name, event.arguments)
            elif isinstance(event, ToolReturn):
                started, name, args = self._open.pop(event.id, (self.clock(), event.name, {}))
                elapsed = self.clock() - started
                self._tool_s += elapsed
                self.record.tools.append(ToolRecord(event.name or name, safe_arguments(args),
                                                    round(elapsed * 1000), bool(event.ok)))
            elif isinstance(event, Done):
                self.record.outcome = event.reason
        except Exception as e:
            log.warning("EV3 log: event not recorded: %s", e)

    def subagent_call(self, name: str, arguments: Any, ok: bool, duration_ms: int,
                      agent: str) -> None:
        try:
            self.record.tools.append(ToolRecord(name, safe_arguments(arguments),
                                                int(duration_ms), bool(ok), agent))
        except Exception as e:
            log.warning("EV3 log: subagent call not recorded: %s", e)

    def finish(self, outcome: str | None = None) -> None:
        """Writes the turn (only once). `outcome` forces the outcome ("interrupted")."""
        if self._done:
            return
        self._done = True
        if self.journal is None:
            return
        try:
            if outcome is not None:
                self.record.outcome = outcome
            total = self.clock() - self._t0
            self.record.model_ms = max(round((total - self._tool_s) * 1000), 0)
            self.journal.write(self.record)
        except Exception as e:
            log.warning("EV3 log: turn not recorded: %s", e)
