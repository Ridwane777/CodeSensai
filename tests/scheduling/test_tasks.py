"""Tests scheduled tasks and their storage - feature [X5], ADR-0016."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sensai.scheduling import tasks as tasks_module
from sensai.scheduling.tasks import (
    ScheduleStoreError,
    Task,
    TaskStore,
    format_interval,
    parse_interval,
    validate_task_id,
)

T0 = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("60", 60), ("300", 300), ("30m", 1800), ("1h", 3600), ("1d", 86400), ("7d", 604800),
     ("90s", 90), (120, 120)],
)
def test_parse_interval_accepts_units(text, seconds):
    assert parse_interval(text) == seconds


@pytest.mark.parametrize("text", ["59", "30s", "0m", "", "abc", "1w", "-5m", "1.5h", True, 10])
def test_parse_interval_refuses_invalid_and_under_a_minute(text):
    with pytest.raises(ValueError):
        parse_interval(text)


def test_format_interval_is_the_inverse_of_the_common_units():
    assert [format_interval(s) for s in (1800, 3600, 86400, 90)] == ["30m", "1h", "1d", "90s"]


@pytest.mark.parametrize("task_id", ["", "A", "a b", "../x", "a/b", "x" * 41, "é"])
def test_invalid_ids_are_refused(task_id):
    with pytest.raises(ValueError):
        validate_task_id(task_id)


def test_valid_id_is_kept():
    assert validate_task_id("resume-2") == "resume-2"


def test_task_never_run_is_due_immediately():
    assert Task(id="a", prompt="p", interval_s=3600).is_due(T0)


def test_task_is_due_only_once_the_interval_has_elapsed():
    task = Task(id="a", prompt="p", interval_s=3600, last_run_at=T0.isoformat())
    assert not task.is_due(T0 + timedelta(seconds=3599))
    assert task.is_due(T0 + timedelta(seconds=3600))
    assert task.is_due(T0 + timedelta(days=3))  # no catch-up: a single run


def test_disabled_task_is_never_due():
    assert not Task(id="a", prompt="p", interval_s=60, enabled=False).is_due(T0)


def test_store_round_trip(tmp_path):
    store = TaskStore(tmp_path / "schedule" / "tasks.json")
    assert store.load() == []
    task = Task(id="a", prompt="Summarize", interval_s=3600, tools=["echo"], timeout_s=30)
    store.add(task)
    store.add(Task(id="b", prompt="x", interval_s=60))
    loaded = TaskStore(store.path).load()
    assert [t.id for t in loaded] == ["a", "b"]
    assert loaded[0] == task
    assert loaded[1].tools is None
    assert json.loads(store.path.read_text(encoding="utf-8"))[1].get("tools") is None


def test_duplicate_id_is_refused_and_file_unchanged(tmp_path):
    store = TaskStore(tmp_path / "tasks.json")
    store.add(Task(id="a", prompt="p", interval_s=60))
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        store.add(Task(id="a", prompt="autre", interval_s=120))
    assert store.path.read_bytes() == before


def test_update_and_remove(tmp_path):
    store = TaskStore(tmp_path / "tasks.json")
    store.add(Task(id="a", prompt="p", interval_s=60))
    assert store.update("a", enabled=False, last_status="ok")
    assert store.get("a").enabled is False
    assert not store.update("zzz", enabled=True)
    assert store.remove("a")
    assert not store.remove("a")
    assert store.load() == []


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b'{"id": "a"}',  # an object instead of a list
        b'[{"id": "a"}]',  # missing prompt
        b'[{"id": "A!", "prompt": "p", "interval_s": 60, "created_at": "2026-10-14T08:00:00"}]',
        b'[{"id": "a", "prompt": "p", "interval_s": 5, "created_at": "2026-10-14T08:00:00"}]',
        b'[{"id": "a", "prompt": "p", "interval_s": 60, "created_at": "hier"}]',
        b'[{"id": "a", "prompt": "p", "interval_s": 60, "created_at": "2026-10-14T08:00:00",'
        b' "unknown": 1}]',
        b"\xff\xfe",
    ],
)
def test_corrupt_file_raises_and_is_never_rewritten(tmp_path, content):
    path = tmp_path / "tasks.json"
    path.write_bytes(content)
    store = TaskStore(path)
    with pytest.raises(ScheduleStoreError):
        store.load()
    with pytest.raises(ScheduleStoreError):
        store.add(Task(id="b", prompt="p", interval_s=60))
    with pytest.raises(ScheduleStoreError):
        store.update("a", enabled=False)
    assert path.read_bytes() == content


def test_duplicate_ids_in_file_are_a_corruption(tmp_path):
    store = TaskStore(tmp_path / "tasks.json")
    one = Task(id="a", prompt="p", interval_s=60).to_dict()
    store.path.write_text(json.dumps([one, one]), encoding="utf-8")
    with pytest.raises(ScheduleStoreError, match="duplicate"):
        store.load()


def test_save_is_atomic_through_a_temp_file_and_replace(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.json")
    store.add(Task(id="a", prompt="p", interval_s=60))
    replaced = []
    real_replace = tasks_module.os.replace

    def spy(src, dst):
        replaced.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(tasks_module.os, "replace", spy)
    store.update("a", enabled=False)
    assert len(replaced) == 1
    src, dst = replaced[0]
    assert str(dst) == str(store.path)
    assert str(src) != str(dst)
    assert Path(src).parent == tmp_path  # same folder: os.replace stays atomic


def test_failed_save_leaves_the_old_file_and_no_temp_file(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.json")
    store.add(Task(id="a", prompt="p", interval_s=60))
    before = store.path.read_bytes()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(tasks_module.os, "replace", boom)
    with pytest.raises(OSError):
        store.update("a", enabled=False)
    assert store.path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["tasks.json"]
