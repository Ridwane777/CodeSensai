"""Faux éléments communs aux tests de la planification (X5)."""
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
    """Outil qui compte ses exécutions : sert à prouver qu'il n'a PAS tourné."""

    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def __init__(self, name: str, risk: str) -> None:
        self.name = name
        self.description = f"outil {risk} de test"
        self.risk = risk
        self.calls: list[dict] = []

    def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(ok=True, content="fait")


def say(text: str):
    """Agent factice : répond `text` puis termine."""
    from sensai.core.events import Done, Token

    def agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
        yield Token(text=text)
        yield Done()

    return agent


def add(scheduler, task_id="a", **kwargs):
    """Ajoute une tâche au fichier du planificateur."""
    from sensai.scheduling.tasks import Task

    kwargs.setdefault("prompt", "fais ceci")
    kwargs.setdefault("interval_s", 3600)
    scheduler.store.add(Task(id=task_id, **kwargs))
