"""Shared fakes for the scheduling tests (X5)."""
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from sensai.core.tools import ToolResult

T0 = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: Any) -> None:
        self.now += timedelta(**kwargs)


class FakeTool:
    """Tool that counts its runs: used to prove it did NOT run."""

    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def __init__(self, name: str, risk: str) -> None:
        self.name = name
        self.description = f"{risk} test tool"
        self.risk = risk
        self.calls: list[dict] = []

    def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(ok=True, content="done")


def say(text: str):
    """Fake agent: answers `text`, then finishes."""
    from sensai.core.events import Done, Token

    def agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
        yield Token(text=text)
        yield Done()

    return agent


def add(scheduler, task_id="a", **kwargs):
    """Adds a task to the scheduler file."""
    from sensai.scheduling.tasks import Task

    kwargs.setdefault("prompt", "do this")
    kwargs.setdefault("interval_s", 3600)
    scheduler.store.add(Task(id=task_id, **kwargs))
