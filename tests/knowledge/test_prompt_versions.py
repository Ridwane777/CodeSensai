"""
Tests the prompt version registry — feature [A4], ADR-0010.

The tested principle: a version is immutable, the `active` bookmark moves.
`test_rollback_loses_nothing` is the Definition of Done: go back to an older
version in one command, without deleting anything.
"""
import json

import pytest

from sensai.knowledge.prompt_versions import INDEX_FILE, PromptStore


@pytest.fixture
def store(tmp_path):
    """A registry with a `system` prompt in two versions, v2 active."""
    s = PromptStore(tmp_path)
    s.save("system", "You are CodeSensai.", "initial prompt", author="Alice", date="2026-09-28")
    s.save("system", "You are CodeSensai.\nAnswer in English.", "language", author="Bob",
           date="2026-10-12")
    s.use("system", "v2")
    return s


def test_missing_registry(tmp_path):
    s = PromptStore(tmp_path)

    assert not s.exists()
    assert s.names() == []


def test_first_version_of_a_prompt_becomes_active(tmp_path):
    """Without an active version, the agent would have nothing to read."""
    s = PromptStore(tmp_path)

    assert s.save("memory", "Instruction", "initial", author="Alice") == "v1"
    assert s.active("memory") == "v1"
    assert s.load("memory") == "Instruction"
    assert (tmp_path / "memory" / "v1.txt").read_text(encoding="utf-8") == "Instruction"


def test_save_does_not_move_the_bookmark(store):
    """Store first, put into service later (ADR-0010)."""
    nouvelle = store.save("system", "You are CodeSensai, concise.", "concision", author="Alice")

    assert nouvelle == "v3"
    assert store.active("system") == "v2"


def test_save_refuses_an_already_stored_text(store):
    """US-A4-2: an unchanged text does not create a version."""
    with pytest.raises(ValueError, match="v1"):
        store.save("system", "You are CodeSensai.\n", "duplicate", author="Alice")


def test_history_from_newest_to_oldest(store):
    """US-A4-1: date, author, description, and which version is active."""
    versions = store.history("system")

    assert [v["id"] for v in versions] == ["v2", "v1"]
    assert versions[0] == {
        "id": "v2",
        "date": "2026-10-12",
        "author": "Bob",
        "description": "language",
        "active": True,
    }
    assert versions[1]["active"] is False


def test_rollback_loses_nothing(store):
    """US-A4-3 / DoD: move the bookmark, then go back to the newest."""
    store.use("system", "v1")

    assert store.load("system") == "You are CodeSensai."
    assert [v["id"] for v in store.history("system")] == ["v2", "v1"]

    store.use("system", "v2")
    assert store.load("system").endswith("Answer in English.")


def test_bookmark_kept_on_disk(store, tmp_path):
    """The next `sensai` launch must see the choice."""
    store.use("system", "v1")

    assert PromptStore(tmp_path).active("system") == "v1"


def test_version_given_by_number_only(store):
    assert store.resolve("system", "1") == "v1"
    assert store.resolve("system", "v2") == "v2"


def test_unknown_version_or_prompt(store):
    with pytest.raises(KeyError):
        store.use("system", "v9")
    with pytest.raises(KeyError):
        store.load("nonexistent")


def test_load_a_specific_version(store):
    assert store.load("system", "v1") == "You are CodeSensai."


def test_diff_between_two_versions(store):
    """US-A4-1: line-by-line differences, v2 = the active one by default."""
    diff = store.diff("system", "v1")

    assert "+Answer in English." in diff
    assert "system v1" in diff and "system v2" in diff


def test_diff_of_identical_versions_is_empty(store):
    assert store.diff("system", "v2", "v2") == ""


def test_readable_index_and_versions_stored_per_prompt(store, tmp_path):
    index = json.loads((tmp_path / INDEX_FILE).read_text(encoding="utf-8"))

    assert index["system"]["active"] == "v2"
    assert [v["id"] for v in index["system"]["versions"]] == ["v1", "v2"]
    assert (tmp_path / "system" / "v2.txt").is_file()


def test_consistent_registry(store):
    assert store.check() == []


def test_modified_version_detected(store, tmp_path):
    """A stored version must never change: CI reports it."""
    (tmp_path / "system" / "v1.txt").write_text("silently modified", encoding="utf-8")

    problemes = store.check()

    assert any("system v1" in p for p in problemes)


def test_missing_version_file_detected(store, tmp_path):
    (tmp_path / "system" / "v2.txt").unlink()

    assert any("system v2" in p for p in store.check())


def test_duplicate_numbers_detected(store, tmp_path):
    """Two branches that each create a v2, merged by hand."""
    chemin = tmp_path / INDEX_FILE
    index = json.loads(chemin.read_text(encoding="utf-8"))
    index["system"]["versions"].append(dict(index["system"]["versions"][1]))
    chemin.write_text(json.dumps(index), encoding="utf-8")

    assert any("duplicate" in p for p in PromptStore(tmp_path).check())


def test_bookmark_to_nonexistent_version_detected(store, tmp_path):
    chemin = tmp_path / INDEX_FILE
    index = json.loads(chemin.read_text(encoding="utf-8"))
    index["system"]["active"] = "v7"
    chemin.write_text(json.dumps(index), encoding="utf-8")

    assert any("v7" in p for p in PromptStore(tmp_path).check())
