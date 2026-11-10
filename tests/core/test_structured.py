"""`/structured` and run_structured_query (T5, ADR-0036) — without Ollama."""
import json

import pytest

from sensai.core.ollama_client import OllamaError
from sensai.core.structured import (
    StructuredOutputError,
    handle_structured_command,
    is_structured_command,
    run_structured_query,
)


class FakeOllama:
    """Replaces stream_chat_messages: replays a pre-written answer, or raises."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, host, model, messages, tools=None, format=None, options=None):
        self.calls.append({"host": host, "model": model, "messages": messages, "format": format,
                           "options": options})
        if isinstance(self.reply, Exception):
            raise self.reply
        yield {"content": self.reply}


@pytest.fixture
def fake(monkeypatch):
    def install(reply):
        ollama = FakeOllama(reply)
        monkeypatch.setattr("sensai.core.structured.stream_chat_messages", ollama)
        return ollama
    return install


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_returns_the_parsed_json(fake):
    fake('{"ok": true}')
    assert run_structured_query("http://h:1", "m1", "question", SCHEMA) == {"ok": True}


def test_passes_the_schema_in_the_format_field(fake):
    ollama = fake('{"ok": true}')
    run_structured_query("http://h:1", "m1", "question", SCHEMA)
    assert ollama.calls[0]["format"] == SCHEMA


def test_invalid_json_raises_an_explicit_error(fake):
    fake("this is not json")
    with pytest.raises(StructuredOutputError, match="invalid JSON"):
        run_structured_query("http://h:1", "m1", "question", SCHEMA)


def test_ollama_failure_becomes_structured_output_error(fake):
    fake(OllamaError("Ollama is not responding (timeout)."))
    with pytest.raises(StructuredOutputError, match="timeout"):
        run_structured_query("http://h:1", "m1", "question", SCHEMA)


@pytest.mark.parametrize("line", ['/structured s.json "do X"', "/structured x"])
def test_lines_starting_with_the_command_are_recognized(line):
    assert is_structured_command(line)


def test_anything_else_is_not_recognized():
    assert not is_structured_command("why does /structured fail?")


def test_too_few_arguments_shows_usage():
    out = handle_structured_command("/structured schema.json", host="h", model="m")
    assert "Usage" in out


def test_missing_schema_is_reported(tmp_path):
    missing = tmp_path / "absent.json"
    out = handle_structured_command(
        f"/structured {missing} \"fais X\"", host="h", model="m"
    )
    assert "[Error]" in out and str(missing) in out


def test_malformed_schema_is_reported(tmp_path):
    bad = tmp_path / "schema.json"
    bad.write_text("{not json", encoding="utf-8")
    out = handle_structured_command(f'/structured {bad} "do X"', host="h", model="m")
    assert "[Error]" in out


def test_full_command_returns_formatted_json(tmp_path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")

    def query(host, model, prompt, schema):
        assert schema == SCHEMA
        assert prompt == "do X"
        return {"ok": True}

    out = handle_structured_command(
        f'/structured {schema_file} "do X"', host="h", model="m", query=query
    )
    assert json.loads(out) == {"ok": True}


def test_model_error_is_reported_without_raising(tmp_path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")

    def query(host, model, prompt, schema):
        raise StructuredOutputError("non-conforming answer")

    out = handle_structured_command(
        f'/structured {schema_file} "do X"', host="h", model="m", query=query
    )
    assert "[Error]" in out


# --- Answer grounded in the project (ADR-0039) -------------------------------------------


def test_with_gather_the_agent_answer_is_the_source(tmp_path):
    """Real trial run on 2026-10-24: without tools, /structured made up the functions
    of stats.py. The agent searches first (with its tools), then the schema-based
    formatting relies only on what it found."""
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")
    asked = []

    def gather(prompt):
        asked.append(prompt)
        return "stats.py defines only one function: maximum."

    def query(host, model, prompt, schema):
        assert "do X" in prompt
        assert "stats.py defines only one function: maximum." in prompt
        return {"ok": True}

    out = handle_structured_command(
        f'/structured {schema_file} "do X"', host="h", model="m", query=query, gather=gather
    )
    assert asked == ["do X"]
    assert json.loads(out) == {"ok": True}


def test_search_failure_is_reported_without_structured_call(tmp_path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")

    def gather(prompt):
        raise StructuredOutputError("Ollama is not responding")

    def query(*args):
        raise AssertionError("no formatting without a search")

    out = handle_structured_command(
        f'/structured {schema_file} "do X"', host="h", model="m", query=query, gather=gather
    )
    assert out.startswith("[Error]") and "Ollama is not responding" in out


def test_the_schema_is_checked_before_starting_the_search(tmp_path):
    def gather(prompt):
        raise AssertionError("missing schema: nothing must start")

    out = handle_structured_command(
        f'/structured {tmp_path / "absent.json"} "do X"', host="h", model="m", gather=gather
    )
    assert "[Error]" in out


def test_num_ctx_is_sent_in_the_call_options(fake):
    """PR #97 review: without it, Ollama silently truncates a long prompt."""
    ollama = fake('{"ok": true}')
    run_structured_query("http://h:1", "m1", "question", SCHEMA, num_ctx=4096)
    assert ollama.calls[0]["options"] == {"num_ctx": 4096}


def test_without_num_ctx_no_option_is_sent(fake):
    ollama = fake('{"ok": true}')
    run_structured_query("http://h:1", "m1", "question", SCHEMA)
    assert ollama.calls[0]["options"] is None


def test_the_command_forwards_num_ctx_to_the_call(fake, tmp_path):
    ollama = fake('{"ok": true}')
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    out = handle_structured_command(
        f'/structured {schema} "do X"', host="h", model="m", num_ctx=2048
    )
    assert json.loads(out) == {"ok": True}
    assert ollama.calls[0]["options"] == {"num_ctx": 2048}
