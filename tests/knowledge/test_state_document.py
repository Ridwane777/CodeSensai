"""
Tests the project state document - feature [M4], ADR-0029.

The test that carries the DoD is `test_other_sections_stay_byte_identical`:
it fails if an update touches anything other than the target section, which
would amount to "rewriting the whole document".
"""
import json

import pytest

from sensai.knowledge.state_document import (
    DEFAULT_SECTIONS,
    MAX_PROMPT_CHARS,
    STATE_FILE,
    StateDocument,
    StateError,
)

HAND_WRITTEN = """# Project state

Preamble written by the human.

## Done

- Base Loop
- M1: sessions

## In progress

- R2

## Decisions

- SQLite everywhere, no Postgres (see ADR-0007).

## Known issues

- Indexing is slow.

## Personal notes

A section added by hand.
"""


@pytest.fixture
def doc(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return StateDocument(project, tmp_path / "data" / "state" / "journal.jsonl")


def write(doc, text=HAND_WRITTEN):
    doc.path.write_text(text, encoding="utf-8")


# --- US-M4-1: a readable file, created with the default sections --------------


def test_file_lives_in_the_project(doc):
    assert doc.path.name == STATE_FILE == "SENSAI.md"
    assert doc.path.parent == doc.project


def test_first_update_creates_default_sections(doc):
    doc.update("In progress", "replace", "- M4: state document")

    text = doc.path.read_text(encoding="utf-8")
    for section in DEFAULT_SECTIONS:
        assert f"## {section}\n" in text
    assert "- M4: state document" in text
    assert doc.sections() == list(DEFAULT_SECTIONS)


def test_sections_read_in_order_including_hand_added_ones(doc):
    write(doc)

    assert doc.sections() == ["Done", "In progress", "Decisions", "Known issues", "Personal notes"]


# --- US-M4-2: targeted update, never destructive ------------------------


def test_other_sections_stay_byte_identical(doc):
    write(doc)
    before = doc.path.read_text(encoding="utf-8")

    doc.update("In progress", "replace", "- M4\n- R2 (reranking)")

    after = doc.path.read_text(encoding="utf-8")
    assert "- M4\n- R2 (reranking)" in after
    assert "\n- R2\n" not in after
    # Everything before "## In progress" and everything from "## Decisions" on is intact.
    start = before.index("## In progress")
    rest = before.index("## Decisions")
    assert after.startswith(before[:start])
    assert after.endswith(before[rest:])


def test_append_adds_to_end_of_section(doc):
    write(doc)

    doc.update("Done", "append", "- R1 : RAG")

    text = doc.path.read_text(encoding="utf-8")
    assert "## Done\n\n- Base Loop\n- M1: sessions\n- R1 : RAG\n\n## In progress" in text


def test_last_section_can_be_changed(doc):
    write(doc)

    doc.update("Personal notes", "append", "One more note.")

    assert doc.path.read_text(encoding="utf-8").endswith(
        "A section added by hand.\nOne more note.\n"
    )


def test_unknown_section_rejected_with_list_and_file_intact(doc):
    write(doc)

    with pytest.raises(StateError) as error:
        doc.update("Roadmap", "append", "- X")

    assert "Done" in str(error.value) and "In progress" in str(error.value)
    assert doc.path.read_text(encoding="utf-8") == HAND_WRITTEN


@pytest.mark.parametrize("content", ["## Hidden section\n- x", "- ok\n# Title", "  ## indented"])
def test_heading_in_content_is_rejected(doc, content):
    """Otherwise the model could create a section or break the splitting."""
    write(doc)

    with pytest.raises(StateError):
        doc.update("In progress", "replace", content)

    assert doc.path.read_text(encoding="utf-8") == HAND_WRITTEN


def test_unknown_action_rejected(doc):
    write(doc)

    with pytest.raises(StateError):
        doc.update("In progress", "delete", "x")


def test_empty_append_rejected(doc):
    write(doc)

    with pytest.raises(StateError):
        doc.update("Done", "append", "   ")


def test_interrupted_write_leaves_no_half_written_file(doc, monkeypatch):
    write(doc)
    import os

    def failure(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failure)

    with pytest.raises(OSError):
        doc.update("In progress", "replace", "- something else")

    assert doc.path.read_text(encoding="utf-8") == HAND_WRITTEN
    assert [p.name for p in doc.project.iterdir()] == [STATE_FILE]


# --- US-M4-3: view, trace, undo ------------------------------------------


def test_preview_shows_section_before_and_after_without_writing(doc):
    write(doc)

    preview = doc.preview("In progress", "replace", "- M4")

    assert "-- R2" in preview or "- - R2" in preview
    assert "+- M4" in preview
    assert doc.path.read_text(encoding="utf-8") == HAND_WRITTEN


def test_every_update_is_logged(doc):
    write(doc)

    doc.update("In progress", "replace", "- M4", summary="M4 started")

    lines = doc.journal_path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[-1])
    assert entry["section"] == "In progress"
    assert entry["action"] == "replace"
    assert entry["before"].strip() == "- R2"
    assert entry["after"].strip() == "- M4"
    assert entry["summary"] == "M4 started"
    assert entry["date"]
    assert doc.history()[0]["section"] == "In progress"


def test_undo_restores_previous_section_state(doc):
    write(doc)
    doc.update("In progress", "replace", "- M4")

    message = doc.undo("In progress")

    assert doc.path.read_text(encoding="utf-8") == HAND_WRITTEN
    assert "In progress" in message
    assert doc.history()[0]["action"] == "undo"


def test_undo_refused_if_section_was_edited_by_hand(doc):
    write(doc)
    doc.update("In progress", "replace", "- M4")
    text = doc.path.read_text(encoding="utf-8").replace("- M4", "- M4 (fixed by hand)")
    doc.path.write_text(text, encoding="utf-8")

    with pytest.raises(StateError):
        doc.undo("In progress")

    assert "fixed by hand" in doc.path.read_text(encoding="utf-8")


def test_undo_without_history_refused(doc):
    write(doc)

    with pytest.raises(StateError):
        doc.undo("Done")


def test_log_is_per_project(tmp_path):
    a = StateDocument(tmp_path / "a", tmp_path / "journal-a.jsonl")
    b = StateDocument(tmp_path / "b", tmp_path / "journal-b.jsonl")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    a.update("Done", "append", "- a")

    assert b.history() == []


# --- System prompt (ADR-0029, decision 4) ------------------------------------


def test_no_file_no_prompt(doc):
    assert doc.as_prompt() == ""


def test_prompt_framed_as_data(doc):
    write(doc)

    prompt = doc.as_prompt()

    assert "SENSAI.md" in prompt
    assert "- SQLite everywhere" in prompt
    assert "data" in prompt.lower() and "not instructions" in prompt.lower()


def test_prompt_truncated_past_limit(doc):
    write(doc, "## Done\n\n" + "- done task\n" * 2000)

    prompt = doc.as_prompt()

    assert len(prompt) <= MAX_PROMPT_CHARS + 500
    assert "truncated" in prompt


def test_two_undos_go_back_two_changes(doc):
    """Like Ctrl+Z (ADR-0029, choice made after the real trial run of 2026-10-17):
    one more undo goes back one more change; it does not undo the previous
    undo."""
    write(doc)
    doc.update("In progress", "replace", "- M4")
    doc.update("In progress", "replace", "- M4 and R2")

    doc.undo("In progress")
    assert "\n- M4\n" in doc.path.read_text(encoding="utf-8")

    doc.undo("In progress")
    assert doc.path.read_text(encoding="utf-8") == HAND_WRITTEN

    with pytest.raises(StateError):
        doc.undo("In progress")


def test_new_change_after_undo_starts_from_there(doc):
    write(doc)
    doc.update("In progress", "replace", "- M4")
    doc.undo("In progress")
    doc.update("In progress", "replace", "- R2")

    doc.undo("In progress")

    assert doc.path.read_text(encoding="utf-8") == HAND_WRITTEN
