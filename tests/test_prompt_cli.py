"""
Tests the `sensai-prompt` command end to end — feature [A4], ADR-0010.

`test_dod_history_then_rollback` replays the Definition of Done: show the
prompt history, then go back to an older version in one command.
"""
import pytest

from sensai import prompt_cli
from sensai.knowledge.prompt_versions import PromptStore


@pytest.fixture
def folder(tmp_path):
    s = PromptStore(tmp_path)
    s.save("system", "You are CodeSensai.", "initial prompt", author="Alice", date="2026-09-28")
    s.save("system", "You are CodeSensai.\nBe concise.", "conciseness", author="Bob",
           date="2026-10-12")
    s.use("system", "v2")
    return tmp_path


def run(folder, *args):
    return prompt_cli.main(["--dir", str(folder), *args])


def test_dod_history_then_rollback(folder, capsys):
    assert run(folder, "history", "system") == 0
    out = capsys.readouterr().out
    assert "v2" in out and "2026-10-12" in out and "Bob" in out
    assert "conciseness" in out and "active" in out

    assert run(folder, "use", "system", "v1") == 0

    assert PromptStore(folder).active("system") == "v1"
    assert "v1" in capsys.readouterr().out


def test_show_prints_the_active_version_by_default(folder, capsys):
    run(folder, "show", "system")

    assert capsys.readouterr().out.strip() == "You are CodeSensai.\nBe concise."


def test_show_a_specific_version(folder, capsys):
    run(folder, "show", "system", "1")

    assert capsys.readouterr().out.strip() == "You are CodeSensai."


def test_diff(folder, capsys):
    assert run(folder, "diff", "system", "v1") == 0

    assert "+Be concise." in capsys.readouterr().out


def test_save_from_a_file(folder, tmp_path, capsys):
    draft = tmp_path / "draft.txt"
    draft.write_text("You are CodeSensai, in English.", encoding="utf-8")

    assert run(folder, "save", "system", str(draft), "language") == 0

    store = PromptStore(folder)
    assert store.history("system")[0]["id"] == "v3"
    assert store.active("system") == "v2"
    out = capsys.readouterr().out
    assert "v3" in out and "use system v3" in out


def test_save_of_identical_text_is_refused(folder, tmp_path, capsys):
    draft = tmp_path / "draft.txt"
    draft.write_text("You are CodeSensai.", encoding="utf-8")

    assert run(folder, "save", "system", str(draft), "duplicate") == 1
    assert "v1" in capsys.readouterr().err


def test_unknown_version_clear_message(folder, capsys):
    assert run(folder, "use", "system", "v9") == 1
    assert "v9" in capsys.readouterr().err


def test_missing_draft_file(folder, capsys):
    assert run(folder, "save", "system", "does_not_exist.txt", "x") == 1
    assert "does_not_exist.txt" in capsys.readouterr().err


def test_check(folder, capsys):
    assert run(folder, "check") == 0

    (folder / "system" / "v1.txt").write_text("modified", encoding="utf-8")
    assert run(folder, "check") == 1
    assert "system v1" in capsys.readouterr().err
