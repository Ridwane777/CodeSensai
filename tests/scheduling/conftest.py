"""Fixtures communes aux tests de la planification (X5)."""
import pytest

from sensai.core.tools import ToolRegistry
from sensai.scheduling.runner import Scheduler
from sensai.scheduling.tasks import TaskStore

from .helpers import FakeClock, FakeTool, say


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def registry():
    reg = ToolRegistry()
    for name, risk in (("lire", "read"), ("chercher", "network"), ("ecrire", "write"),
                       ("lancer", "execute")):
        reg.register(FakeTool(name, risk))
    return reg


@pytest.fixture
def make_scheduler(tmp_path, clock):
    def make(**kwargs) -> Scheduler:
        base = tmp_path / "schedule"
        kwargs.setdefault("agent", say("bonjour"))
        return Scheduler(
            TaskStore(base / "tasks.json"), base, host="h", model="m", clock=clock, **kwargs
        )

    return make
