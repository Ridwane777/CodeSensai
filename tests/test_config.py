"""
Tests configuration path resolution.

The test that matters is `test_prompt_found_from_another_folder`: it fails if
someone brings back a read relative to the current folder, which would start
the agent without a system prompt as soon as it runs outside the repository.
"""
import json
import os

import pytest

from sensai.config import (
    get_settings,
    load_config_file,
    load_system_prompt,
    num_ctx_from_config,
    resolve_path,
)
from sensai.knowledge.compression import DEFAULT_NUM_CTX, budget_from_num_ctx
from sensai.knowledge.prompt_versions import PromptStore


def test_prompt_found_from_another_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    assert get_settings()["system_prompt"] != ""
    assert load_config_file()["model"]


def test_prompts_read_from_the_active_version(tmp_path, monkeypatch):
    """A4 (ADR-0010): the agent reads the version that carries the bookmark."""
    monkeypatch.chdir(tmp_path)
    store = PromptStore(tmp_path / "prompts")
    store.save("system", "System v1", "initial", author="Alice")
    store.save("system", "System v2", "follow-up", author="Alice")
    store.save("memory", "Memory v1", "initial", author="Alice")
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["system_prompt"] == "System v1"
    assert settings["memory_prompt"] == "Memory v1"
    assert settings["prompt_versions"] == {"system": "v1", "memory": "v1"}

    store.use("system", "v2")
    assert get_settings()["system_prompt"] == "System v2"


def test_draft_passed_as_option_takes_precedence(tmp_path, monkeypatch):
    """Try a draft before storing it: --system-prompt wins."""
    monkeypatch.chdir(tmp_path)
    store = PromptStore(tmp_path / "prompts")
    store.save("system", "Stored system", "initial", author="Alice")
    store.save("memory", "Memory", "initial", author="Alice")
    (tmp_path / "brouillon.txt").write_text("Brouillon", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai", "--system-prompt", "brouillon.txt"])

    settings = get_settings()

    assert settings["system_prompt"] == "Brouillon"
    assert settings["prompt_versions"]["system"] == "brouillon.txt (not registered)"
    assert settings["prompt_versions"]["memory"] == "v1"


def test_without_registry_legacy_files_are_read(tmp_path, monkeypatch):
    """Fallback until the other branches have merged A4."""
    root = tmp_path / "repo"
    (root / "prompts").mkdir(parents=True)
    (root / "prompts" / "system_prompt.txt").write_text("Legacy system", encoding="utf-8")
    (root / "prompts" / "memory_prompt.txt").write_text("Legacy memory", encoding="utf-8")
    monkeypatch.setattr("sensai.config.PROJECT_ROOT", root)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["system_prompt"] == "Legacy system"
    assert settings["memory_prompt"] == "Legacy memory"
    assert settings["prompt_versions"] == {}


def test_resume_instruction_loaded_from_a_file(tmp_path, monkeypatch):
    """Like the system prompt: a file in prompts/, never a constant."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    assert "history" in get_settings()["memory_prompt"]


def test_current_folder_takes_precedence(tmp_path, monkeypatch):
    """A config.json placed next to the user's project must win."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text('{"model": "mistral"}', encoding="utf-8")

    assert load_config_file()["model"] == "mistral"


def test_missing_file_does_not_raise():
    assert resolve_path("does_not_exist.txt") is None
    assert load_system_prompt("does_not_exist.txt") == ""
    assert load_config_file("does_not_exist.json") == {}


def test_absolute_path_is_honored(tmp_path):
    file_path = tmp_path / "prompt.txt"
    file_path.write_text("  hello  ", encoding="utf-8")

    assert load_system_prompt(os.fspath(file_path)) == "hello"


def test_retention_default_and_configurable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])
    assert get_settings()["retention_days"] == 30

    (tmp_path / "config.json").write_text('{"retention_days": 90}', encoding="utf-8")
    assert get_settings()["retention_days"] == 90

    monkeypatch.setattr("sys.argv", ["sensai", "--retention-days", "0"])
    assert get_settings()["retention_days"] == 0


def test_negative_retention_is_refused(tmp_path, monkeypatch):
    """A negative duration would purge everything: refuse instead of guessing."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai", "--retention-days", "-1"])

    with pytest.raises(SystemExit):
        get_settings()


def test_default_rag_settings(tmp_path, monkeypatch):
    """Values decided in ADR-0009, measured in docs/performance/R1-rag.md."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["rag"] is True
    assert settings["rag_model"] == "bge-m3"
    assert settings["rag_min_score"] == 0.54
    assert settings["rag_top_k"] == 5


def test_rag_can_be_disabled_and_threshold_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text('{"rag_min_score": 0.6}', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai", "--no-rag"])

    settings = get_settings()

    assert settings["rag"] is False
    assert settings["rag_min_score"] == 0.6


def test_out_of_range_threshold_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai", "--rag-min-score", "1.5"])

    with pytest.raises(SystemExit):
        get_settings()


def test_tools_and_files_settings_are_read(tmp_path, monkeypatch):
    """ADR-0011 and the tool contract: the `tools` and `files` sections of
    config.json apply to the CLI, not only to the scheduler."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(
        '{"tools": {"disabled": ["web_search"], "tool_timeout_s": 30},'
        ' "files": {"read": ["docs"], "write": ["docs"]}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["tool_preferences"].disabled == frozenset({"web_search"})
    assert settings["tool_preferences"].tool_timeout_s == 30
    assert settings["file_permissions"].read_roots == ((tmp_path / "docs").resolve(),)


def test_without_section_defaults_apply(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["tool_preferences"].disabled == frozenset()
    assert settings["file_permissions"].read_roots == (tmp_path.resolve(),)


@pytest.mark.parametrize("section", ['"tools": {"dsabled": []}', '"files": {"reed": ["."]}'])
def test_typo_in_config_is_refused(tmp_path, monkeypatch, section):
    """A misspelled restriction must not be silently ignored: one would
    believe the tool disabled when it is not."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text("{" + section + "}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai"])

    with pytest.raises(SystemExit):
        get_settings()


@pytest.mark.parametrize("personas", [
    '"abc"',
    '{"profiles": ["x"]}',
    '{"profiles": [{"id": ["a"], "name": "n", "role": "r", "tone": "t", "scope": "s"}]}',
    '{"profiles": [{"id": "a", "name": 1, "role": "r", "tone": "t", "scope": "s"}]}',
    '{"profiles": [{"id": "a", "name": "", "role": "r", "tone": "t", "scope": "s"}]}',
    '{"profiles": [{"id": "a", "name": "n", "role": "r", "tone": "t", "scope": "s"}],'
    ' "default": "unknown"}',
])
def test_malformed_persona_stops_the_cli_with_a_message(tmp_path, monkeypatch, capsys, personas):
    """PR #94 review: an invalid `personas` section gives a readable
    `parser.error` (code 2), never a Python traceback."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(
        '{"personas": ' + personas + "}", encoding="utf-8"
    )
    monkeypatch.setattr("sys.argv", ["sensai"])

    with pytest.raises(SystemExit) as sortie:
        get_settings()

    assert sortie.value.code == 2
    assert "config.json: personas" in capsys.readouterr().err


def _settings(tmp_path, monkeypatch, argv=(), config=None):
    monkeypatch.chdir(tmp_path)
    if config is not None:
        (tmp_path / "config.json").write_text(config, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai", *argv])
    return get_settings()


def test_default_num_ctx_and_budget(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    assert settings["num_ctx"] == DEFAULT_NUM_CTX
    assert settings["token_budget_max"] == budget_from_num_ctx(DEFAULT_NUM_CTX)


@pytest.mark.parametrize("num_ctx", [4096, 32768])
def test_budget_follows_command_line_num_ctx(tmp_path, monkeypatch, num_ctx):
    """PR #97 review: `--num-ctx 4096` left the budget at 6192, larger than the
    window - Ollama truncated before summarization kicked in."""
    settings = _settings(tmp_path, monkeypatch, ["--num-ctx", str(num_ctx)])
    assert settings["num_ctx"] == num_ctx
    assert settings["token_budget_max"] == budget_from_num_ctx(num_ctx)


def test_budget_follows_config_json_num_ctx(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch, config='{"num_ctx": 16384}')
    assert settings["token_budget_max"] == budget_from_num_ctx(16384)


def test_command_line_overrides_config_json_for_num_ctx(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch, ["--num-ctx", "4096"], '{"num_ctx": 16384}')
    assert settings["token_budget_max"] == budget_from_num_ctx(4096)


def test_explicit_budget_is_not_recomputed(tmp_path, monkeypatch):
    argv = ["--num-ctx", "32768", "--token-budget-max", "5000"]
    settings = _settings(tmp_path, monkeypatch, argv)
    assert settings["token_budget_max"] == 5000
    settings = _settings(tmp_path, monkeypatch, config='{"token_budget_max": 3000}')
    assert settings["token_budget_max"] == 3000


def test_budget_exceeding_the_window_is_refused(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _settings(tmp_path, monkeypatch, ["--num-ctx", "4096", "--token-budget-max", "5000"])
    assert "--token-budget-max" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", '"8192"', "true", "1.5"])
def test_invalid_num_ctx_in_config_json_is_refused(value):
    with pytest.raises(ValueError, match="num_ctx"):
        num_ctx_from_config({"num_ctx": json.loads(value)})


def test_default_num_ctx_for_schedule_and_eval():
    assert num_ctx_from_config({}) == DEFAULT_NUM_CTX
    assert num_ctx_from_config({"num_ctx": 4096}) == 4096


# --- Generation parameters and step count (ADR-0057) ------------------------

def test_generation_parameters_defaults_and_overrides(tmp_path, monkeypatch):
    """Generation parameters go through the configuration."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({"generation": {"temperature": 0.5, "seed": 42}, "max_iterations": 9}),
        encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai", "--top-p", "0.8"])
    settings = get_settings()
    assert settings["generation"] == {"temperature": 0.5, "top_p": 0.8, "seed": 42}
    assert settings["max_iterations"] == 9


def test_unknown_generation_parameter_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text('{"generation": {"temprature": 0.1}}', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai"])
    with pytest.raises(SystemExit):
        get_settings()


def test_readers_for_schedule_and_eval():
    from sensai.config import DEFAULT_GENERATION, generation_from_config, max_iterations_from_config

    assert generation_from_config({}) == DEFAULT_GENERATION
    assert generation_from_config({"generation": {"temperature": 0}})["temperature"] == 0
    assert max_iterations_from_config({}) == 6
    with pytest.raises(ValueError):
        generation_from_config({"generation": {"temp": 1}})
    with pytest.raises(ValueError):
        max_iterations_from_config({"max_iterations": 0})


def test_cache_is_disabled_by_default(tmp_path, monkeypatch):
    """ADR-0056 : A6 devient optionnel (`--cache` ou "cache": true)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])
    assert get_settings()["cache"] is False
    monkeypatch.setattr("sys.argv", ["sensai", "--cache"])
    assert get_settings()["cache"] is True


def test_invalid_request_timeout_in_config_json_stops_the_cli(tmp_path, monkeypatch):
    """`true` became 1 s once passed to argparse: the CLI must refuse."""
    (tmp_path / "config.json").write_text('{"request_timeout": true}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])
    with pytest.raises(SystemExit):
        get_settings()


def test_request_timeout_from_config_json(tmp_path):
    from sensai.config import request_timeout_from_config
    from sensai.core.ollama_client import DEFAULT_REQUEST_TIMEOUT

    assert request_timeout_from_config({}) == DEFAULT_REQUEST_TIMEOUT
    assert request_timeout_from_config({"request_timeout": 900}) == 900
    for bad in (0, -5, "600", True, 1.5):
        with pytest.raises(ValueError, match="request_timeout"):
            request_timeout_from_config({"request_timeout": bad})
