"""
Running scheduled tasks — feature [X5], ADR-0016.

Nobody is in front of the screen when a task runs. The guarantees:

- every tool call goes through a ToolGateway whose confirmer is
  `deny_all`: a tool that asks for confirmation (write, execute) is
  always refused; no preference can loosen this (tool_policy.py);
- a task that crashes does not prevent the following ones;
- the same task never runs twice at the same time (lock file);
- every run leaves a JSON run report.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import shutil
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sensai.core.agent import run_agent_turn
from sensai.core.events import Done, Error, Event, Token
from sensai.core.tools import ToolRegistry, ToolResult
from sensai.execution.gateway import ToolGateway, deny_all
from sensai.execution.guardrails import InputRules, check_input, filter_input, filter_output
from sensai.execution.tool_policy import ToolPreferences
from sensai.knowledge.memory import date_block
from sensai.registry import build_registry

from .tasks import Task, TaskStore, atomic_write, parse_time, utc_now, validate_task_id

log = logging.getLogger(__name__)

KEEP_RUNS = 50

OK = "ok"
ERROR = "error"
MAX_ITERATIONS = "max_iterations"
TIMEOUT = "timeout"
SKIPPED_LOCKED = "skipped_locked"
# Statuses that count as a failure for the command exit code.
FAILED_STATUSES = frozenset({ERROR, MAX_ITERATIONS, TIMEOUT})

UNATTENDED_NOTE = (
    "This task runs unattended: nobody can confirm an action. "
    "If a tool is refused, do not retry it: do not insist and do not work around the refusal. "
    "Finish by stating clearly what you could not do."
)

Agent = Callable[[str, str, list[dict], Any], Iterator[Event]]
GatewayFactory = Callable[[Task], Any]


def runs_path(base_dir: Path, task_id: str) -> Path:
    # Defense in depth: an id must never escape the directory.
    return base_dir / "runs" / validate_task_id(task_id)


def lock_path(base_dir: Path, task_id: str) -> Path:
    return base_dir / "locks" / f"{validate_task_id(task_id)}.lock"


def delete_runs(base_dir: Path, task_id: str) -> None:
    shutil.rmtree(runs_path(base_dir, task_id), ignore_errors=True)


def list_runs(base_dir: Path, task_id: str) -> list[dict]:
    """Run reports of a task, newest first. Unreadable files are skipped:
    a damaged run report must not block anything."""
    folder = runs_path(base_dir, task_id)
    if not folder.is_dir():
        return []
    records = []
    for path in sorted(folder.glob("*.json"), reverse=True):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("unreadable run report skipped: %s", path)
    return records


def unattended_preferences(
    base: ToolPreferences, registry: ToolRegistry, allowed: list[str] | None
) -> ToolPreferences:
    """Preferences for an unattended run.

    `confirm_after_untrusted` is forced: after reading untrusted content, no
    non-read tool runs without confirmation — so, here, none at all. An
    `allowed` list removes the other tools from what the model sees. `modes`
    is left alone: the policy ignores any loosening for WRITE and EXECUTE
    anyway.
    """
    disabled = set(base.disabled)
    if allowed is not None:
        keep = set(allowed)
        disabled |= {d["name"] for d in registry.describe_all() if d["name"] not in keep}
    return dataclasses.replace(
        base, disabled=frozenset(disabled), confirm_after_untrusted=True
    )


def build_unattended_gateway(
    registry: ToolRegistry, base: ToolPreferences, allowed: list[str] | None = None
) -> ToolGateway:
    """A fresh gateway per run: the "untrusted content read" state does not
    leak from one task to another. `deny_all` is passed explicitly."""
    gateway = ToolGateway(
        registry,
        unattended_preferences(base, registry, allowed),
        confirm=deny_all,
        # Nobody reviews what a tool returns: secrets are masked
        # before the model and the run report (EV4, OUT-15).
        input_guards=[check_input],
        output_filters=[filter_output],
    )
    gateway.reset_untrusted()
    return gateway


class _RecordingGateway:
    """Wraps the gateway to keep, per tool call, the name and the outcome
    (ok or error code) — never the arguments, which may contain secrets."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    def describe_all(self) -> list[dict[str, Any]]:
        return self.inner.describe_all()

    def call(self, name: str, /, **kwargs: Any) -> ToolResult:
        try:
            result = self.inner.call(name, **kwargs)
        except Exception:
            self.calls.append({"name": name, "ok": False, "error": "exception"})
            raise
        entry: dict[str, Any] = {"name": name, "ok": result.ok}
        if not result.ok:
            entry["error"] = result.data.get("error", "tool_error")
        self.calls.append(entry)
        return result


class Scheduler:
    def __init__(
        self,
        store: TaskStore,
        base_dir: Path,
        *,
        host: str = "",
        model: str = "",
        system_prompt: str = "",
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        agent: Agent = run_agent_turn,
        gateway_factory: GatewayFactory | None = None,
        registry: ToolRegistry | None = None,
        preferences: ToolPreferences | None = None,
        keep_runs: int = KEEP_RUNS,
        input_rules: InputRules | None = None,
    ) -> None:
        self.store = store
        # The CLI and web input filter (EV2, ADR-0027) also applies to a task
        # prompt: it is replayed with nobody in front of the screen.
        self.input_rules = input_rules
        self.base_dir = Path(base_dir)
        self.host = host
        self.model = model
        self.system_prompt = system_prompt
        self.clock = clock
        self.monotonic = monotonic
        self.agent = agent
        self.registry = registry
        self.preferences = preferences or ToolPreferences()
        self.keep_runs = keep_runs
        self.gateway_factory = gateway_factory or self._default_gateway

    def _default_gateway(self, task: Task) -> ToolGateway:
        if self.registry is None:
            self.registry = build_registry()
        return build_unattended_gateway(self.registry, self.preferences, task.tools)

    # -- what to run ----------------------------------------------------------

    def due_tasks(self, now: datetime | None = None) -> list[Task]:
        now = now or self.clock()
        return [t for t in self.store.load() if t.is_due(now)]

    def run_due(self, now: datetime | None = None) -> list[dict]:
        """One pass: runs each due task, one after the other.

        Raises ScheduleStoreError if the task file is broken (nothing is run
        then). Any other failure is isolated to the task that causes it.
        """
        records = []
        for task in self.due_tasks(now):
            try:
                records.append(self.run_task(task))
            except Exception as exc:  # a broken task must not prevent the following ones
                log.exception("task %s: unexpected failure", task.id)
                records.append(self._salvage(task, exc))
        return records

    def _salvage(self, task: Task, exc: Exception) -> dict:
        """Last resort when run_task itself crashed (disk full, task file became
        unreadable...): record what we can, without raising again."""
        now = self.clock()
        record = self._record(task, now, now, ERROR, error=f"{type(exc).__name__}: {exc}")
        for action in (
            lambda: self._write_record(task.id, record, now),
            lambda: self.store.update(task.id, last_run_at=now.isoformat(), last_status=ERROR),
        ):
            try:
                action()
            except Exception:
                log.exception("task %s: could not record the failure", task.id)
        return record

    def loop(
        self,
        every_s: float,
        sleep: Callable[[float], None] = time.sleep,
        max_passes: int | None = None,
    ) -> None:
        """Calls run_due every `every_s` seconds (fallback mode when there is
        neither cron nor systemd). `sleep` is injectable for tests."""
        passes = 0
        while max_passes is None or passes < max_passes:
            self.run_due()
            passes += 1
            if max_passes is not None and passes >= max_passes:
                break
            sleep(every_s)

    # -- one run ----------------------------------------------------------

    def run_task(self, task: Task) -> dict:
        """Runs `task` now, due or not (`run_due` does the filtering)."""
        started = self.clock()
        lock = self._acquire_lock(task, started)
        if lock is None:
            log.warning("task %s already running: run skipped", task.id)
            record = self._record(
                task, started, started, SKIPPED_LOCKED, error="a run is already in progress"
            )
            self._write_record(task.id, record, started)
            return record
        try:
            try:
                record = self._execute(task, started)
            except Exception as exc:
                log.exception("task %s failed", task.id)
                record = self._record(
                    task, started, self.clock(), ERROR, error=f"{type(exc).__name__}: {exc}"
                )
            self._write_record(task.id, record, started)
            self.store.update(
                task.id, last_run_at=started.isoformat(), last_status=record["status"]
            )
        finally:
            self._release_lock(lock)
        return record

    def _execute(self, task: Task, started: datetime) -> dict:
        gateway = _RecordingGateway(self.gateway_factory(task))
        # A task must not inherit the distrust (or trust) of another one.
        reset = getattr(gateway.inner, "reset_untrusted", None)
        if callable(reset):
            reset()
        # Today's date, computed on every run: a `loop` can run for days
        # (without it, the model thought it was 2024, trial run on 2026-11-01).
        system = f"{UNATTENDED_NOTE}\n\n{date_block()}\n\n{self.system_prompt}".strip()
        allowed, prompt = filter_input(task.prompt, self.input_rules)
        if not allowed:
            # Blocked just like the same text typed in the chat: nothing reaches the model.
            return self._record(task, started, self.clock(), ERROR,
                                error=f"Blocked by the input filter: {prompt}")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        answer: list[str] = []
        error: str | None = None
        reason = "final_answer"
        timed_out = False
        deadline = self.monotonic() + task.timeout_s

        events = self.agent(self.host, self.model, messages, gateway)
        try:
            for event in events:
                if isinstance(event, Token):
                    answer.append(event.text)
                elif isinstance(event, Error):
                    error = event.message
                elif isinstance(event, Done):
                    reason = event.reason
                    break
                # The timeout is only checked between two events: a call
                # stuck in the model or in a tool cannot be
                # interrupted from here (ADR-0016).
                if self.monotonic() >= deadline:
                    timed_out = True
                    break
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    log.exception("task %s: closing the stream failed", task.id)

        if timed_out:
            status, error = TIMEOUT, f"timeout of {task.timeout_s} s exceeded"
        elif error is not None or reason == "error":
            status, error = ERROR, error or "the agent reported an error"
        elif reason == "max_iterations":
            status, error = MAX_ITERATIONS, "maximum number of steps reached without a final answer"
        else:
            status = OK
        return self._record(
            task,
            started,
            self.clock(),
            status,
            answer="".join(answer),
            tool_calls=gateway.calls,
            error=error,
        )

    # -- run reports ----------------------------------------------------------

    @staticmethod
    def _record(
        task: Task,
        started: datetime,
        finished: datetime,
        status: str,
        *,
        answer: str = "",
        tool_calls: list[dict] | None = None,
        error: str | None = None,
    ) -> dict:
        return {
            "task_id": task.id,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "status": status,
            "answer": answer,
            "tool_calls": tool_calls or [],
            "error": error,
        }

    def _write_record(self, task_id: str, record: dict, started: datetime) -> None:
        folder = runs_path(self.base_dir, task_id)
        stamp = started.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        path = folder / f"{stamp}.json"
        n = 0
        while path.exists():  # identical clock (tests, back-to-back --force)
            n += 1
            path = folder / f"{stamp}_{n}.json"
        atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        for old in sorted(folder.glob("*.json"))[: -self.keep_runs]:
            try:
                old.unlink()
            except OSError:
                log.warning("old run report not deleted: %s", old)

    # -- lock ----------------------------------------------------------------

    def _acquire_lock(self, task: Task, now: datetime) -> Path | None:
        """Creates the lock with O_EXCL (atomic). A lock older than twice the
        task timeout is deemed abandoned (killed process) and taken over.

        Simple and time-based: two processes taking over the same stale lock
        at the same instant may overlap (ADR-0016).
        """
        path = lock_path(self.base_dir, task.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if attempt == 0 and self._lock_is_stale(path, task, now):
                    log.warning("task %s: stale lock removed (%s)", task.id, path)
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                return None
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "started_at": now.isoformat()}, f)
            return path
        return None

    @staticmethod
    def _lock_is_stale(path: Path, task: Task, now: datetime) -> bool:
        try:
            started = parse_time(json.loads(path.read_text(encoding="utf-8"))["started_at"])
        except (OSError, ValueError, KeyError, TypeError):
            # Empty or unreadable lock (just created by another process?):
            # rely on the file timestamp.
            try:
                started = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            except OSError:
                return False
        return now - started > timedelta(seconds=2 * task.timeout_s)

    @staticmethod
    def _release_lock(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
