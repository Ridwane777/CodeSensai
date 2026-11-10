"""
Scheduled tasks and their storage — feature [X5], ADR-0016.

A task = a prompt replayed at a fixed interval. Everything lives in a single
JSON file (`<data>/schedule/tasks.json`): a few tasks per user, so nothing
that justifies a database (see the ADR).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

TASKS_FILE = "tasks.json"
# An id is used as a directory name and lock file name: restricted alphabet,
# so that no id can escape the directory ("../x").
ID_PATTERN = re.compile(r"[a-z0-9-]{1,40}")
# Below one minute, a task would overlap itself and saturate Ollama.
MIN_INTERVAL_S = 60
DEFAULT_TIMEOUT_S = 600

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_INTERVAL = re.compile(r"(\d+)\s*([smhd]?)")


class ScheduleStoreError(Exception):
    """The task file is unreadable or has the wrong format.

    The file is never rewritten in that case: it may contain tasks that can
    be recovered by hand.
    """


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_interval(text: str | int) -> int:
    """"30m", "1h", "1d", "7d" or a number of seconds -> seconds.

    Rejects anything below MIN_INTERVAL_S.
    """
    if isinstance(text, bool):
        raise ValueError("Invalid interval.")
    if isinstance(text, int):
        seconds = text
    else:
        match = _INTERVAL.fullmatch(text.strip().lower())
        if match is None:
            raise ValueError(
                f"Invalid interval: {text!r} (examples: 300, 30m, 1h, 1d, 7d)."
            )
        seconds = int(match.group(1)) * _UNITS[match.group(2) or "s"]
    if seconds < MIN_INTERVAL_S:
        raise ValueError(f"Interval too short: {MIN_INTERVAL_S} seconds minimum.")
    return seconds


def format_interval(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def validate_task_id(task_id: str) -> str:
    if not isinstance(task_id, str) or ID_PATTERN.fullmatch(task_id) is None:
        raise ValueError(
            f"Invalid id: {task_id!r} (1 to 40 characters from a-z, 0-9 and \"-\")."
        )
    return task_id


def parse_time(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    # A date without a timezone is read as UTC: never mix naive and aware.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass
class Task:
    id: str
    prompt: str
    interval_s: int
    enabled: bool = True
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    last_run_at: str | None = None
    last_status: str | None = None
    # None = all registry tools; otherwise the list of those to keep.
    tools: list[str] | None = None
    timeout_s: int = DEFAULT_TIMEOUT_S

    def is_due(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        due_at = self.next_due()
        return due_at is None or now >= due_at

    def next_due(self) -> datetime | None:
        """Next due time, or None if the task never ran (due right away)."""
        if self.last_run_at is None:
            return None
        return parse_time(self.last_run_at) + timedelta(seconds=self.interval_s)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "prompt": self.prompt,
            "interval_s": self.interval_s,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "timeout_s": self.timeout_s,
        }
        if self.tools is not None:
            data["tools"] = list(self.tools)
        return data

    @classmethod
    def from_dict(cls, data: Any) -> Task:
        """Raises ValueError if `data` does not have the expected format."""
        if not isinstance(data, dict):
            raise ValueError("a task must be a JSON object")
        unknown = set(data) - {f for f in cls.__dataclass_fields__}
        if unknown:
            raise ValueError(f"unknown keys: {sorted(unknown)}")
        task_id = validate_task_id(data.get("id"))  # type: ignore[arg-type]
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"task {task_id}: 'prompt' must be a non-empty string")
        interval = data.get("interval_s")
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < MIN_INTERVAL_S:
            raise ValueError(
                f"task {task_id}: 'interval_s' must be an integer >= {MIN_INTERVAL_S}"
            )
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"task {task_id}: 'enabled' must be true or false")
        created = data.get("created_at")
        last_run = data.get("last_run_at")
        for key, value in (("created_at", created), ("last_run_at", last_run)):
            if value is None and key == "last_run_at":
                continue
            try:
                parse_time(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                raise ValueError(f"task {task_id}: '{key}' is not an ISO date") from None
        status = data.get("last_status")
        if status is not None and not isinstance(status, str):
            raise ValueError(f"task {task_id}: 'last_status' must be a string")
        tools = data.get("tools")
        if tools is not None and (
            not isinstance(tools, list) or not all(isinstance(t, str) for t in tools)
        ):
            raise ValueError(f"task {task_id}: 'tools' must be a list of tool names")
        timeout = data.get("timeout_s", DEFAULT_TIMEOUT_S)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise ValueError(f"task {task_id}: 'timeout_s' must be an integer > 0")
        return cls(
            id=task_id,
            prompt=prompt,
            interval_s=interval,
            enabled=enabled,
            created_at=created,
            last_run_at=last_run,
            last_status=status,
            tools=tools,
            timeout_s=timeout,
        )


def atomic_write(path: Path, text: str) -> None:
    """Atomic write: temporary file in the same directory, then os.replace.

    A crash (or another process reading) never sees a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> list[Task]:
        """The tasks; empty list if the file does not exist yet.

        Raises ScheduleStoreError if the file is broken — without touching it.
        """
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeDecodeError) as exc:
            raise ScheduleStoreError(f"{self.path} unreadable: {exc}") from exc
        try:
            items = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ScheduleStoreError(f"{self.path} is not valid JSON: {exc}") from exc
        if not isinstance(items, list):
            raise ScheduleStoreError(f"{self.path}: a list of tasks was expected")
        tasks: list[Task] = []
        for item in items:
            try:
                tasks.append(Task.from_dict(item))
            except ValueError as exc:
                raise ScheduleStoreError(f"{self.path}: {exc}") from exc
        ids = [t.id for t in tasks]
        if len(set(ids)) != len(ids):
            raise ScheduleStoreError(f"{self.path}: duplicate task ids")
        return tasks

    def save(self, tasks: list[Task]) -> None:
        """Writes all tasks at once (atomic_write)."""
        payload = json.dumps([t.to_dict() for t in tasks], ensure_ascii=False, indent=2)
        atomic_write(self.path, payload + "\n")

    def get(self, task_id: str) -> Task | None:
        return next((t for t in self.load() if t.id == task_id), None)

    def add(self, task: Task) -> None:
        tasks = self.load()
        if any(t.id == task.id for t in tasks):
            raise ValueError(f"A task \"{task.id}\" already exists.")
        tasks.append(task)
        self.save(tasks)

    def remove(self, task_id: str) -> bool:
        tasks = self.load()
        kept = [t for t in tasks if t.id != task_id]
        if len(kept) == len(tasks):
            return False
        self.save(kept)
        return True

    def update(self, task_id: str, **changes: Any) -> bool:
        """Updates a task, re-reading the file just before: a task added while
        another one runs is not overwritten. False if it has disappeared."""
        tasks = self.load()
        for task in tasks:
            if task.id == task_id:
                for key, value in changes.items():
                    setattr(task, key, value)
                self.save(tasks)
                return True
        return False
