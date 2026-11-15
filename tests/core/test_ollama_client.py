"""The body of requests sent to Ollama (`/api/chat`), without network - M2, ADR-0045."""
import json

import pytest

from sensai.core import ollama_client
from sensai.core.ollama_client import stream_chat, stream_chat_messages


class FakeResponse:
    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield json.dumps({"message": {"content": "ok"}, "done": True}).encode()


def _capture(monkeypatch):
    sent = []

    def fake_post(url, json=None, **kwargs):
        sent.append(json)
        return FakeResponse()

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    return sent


def test_num_ctx_option_is_sent_in_the_body(monkeypatch):
    sent = _capture(monkeypatch)
    list(stream_chat_messages("http://h", "m", [], options={"num_ctx": 4096}))
    assert sent[0]["options"] == {"num_ctx": 4096}


def test_without_options_the_field_is_absent(monkeypatch):
    sent = _capture(monkeypatch)
    list(stream_chat_messages("http://h", "m", []))
    assert "options" not in sent[0]


def test_stream_chat_forwards_num_ctx(monkeypatch):
    """PR #97 review: the `stream_chat` wrapper (used by sensai-eval) dropped it."""
    sent = _capture(monkeypatch)
    assert "".join(stream_chat("http://h", "m", [], num_ctx=8192)) == "ok"
    assert sent[0]["options"] == {"num_ctx": 8192}


def test_stream_chat_without_num_ctx_sends_no_options(monkeypatch):
    sent = _capture(monkeypatch)
    list(stream_chat("http://h", "m", []))
    assert "options" not in sent[0]


# --- Generation parameters (ADR-0057) ---

def test_generation_parameters_are_sent_on_every_call(monkeypatch):
    sent = _capture(monkeypatch)
    ollama_client.set_generation_options({"temperature": 0.2, "top_p": 0.9, "seed": None})
    list(stream_chat("http://h", "m", [], num_ctx=8192))
    assert sent[0]["options"] == {"temperature": 0.2, "top_p": 0.9, "num_ctx": 8192}
    assert ollama_client.generation_options() == {"temperature": 0.2, "top_p": 0.9}


def test_a_per_call_option_overrides_the_global_setting(monkeypatch):
    """What a call sets itself (num_ctx, a temperature of 0...) is not overwritten."""
    sent = _capture(monkeypatch)
    ollama_client.set_generation_options({"temperature": 0.7})
    list(stream_chat_messages("http://h", "m", [], options={"temperature": 0}))
    assert sent[0]["options"] == {"temperature": 0}


# --- Ollama timeout (trial run on 2026-11-06 on CPU) ---

def _capture_timeout(monkeypatch):
    timeouts = []

    def fake_post(url, json=None, timeout=None, **kwargs):
        timeouts.append(timeout)
        return FakeResponse()

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    return timeouts


def test_connect_stays_short_and_read_waits_for_the_cpu(monkeypatch):
    """On CPU, qwen3:8b takes several minutes before the first chunk: 60 s made
    every turn fail; a stopped Ollama must still be reported quickly."""
    timeouts = _capture_timeout(monkeypatch)
    list(stream_chat_messages("http://h", "m", []))
    assert timeouts[0] == (ollama_client.CONNECT_TIMEOUT, ollama_client.DEFAULT_REQUEST_TIMEOUT)
    assert ollama_client.CONNECT_TIMEOUT <= 10 < 300 <= ollama_client.DEFAULT_REQUEST_TIMEOUT


def test_the_timeout_set_at_startup_applies(monkeypatch):
    timeouts = _capture_timeout(monkeypatch)
    ollama_client.set_request_timeout(1200)
    list(stream_chat_messages("http://h", "m", []))
    assert timeouts[0][1] == 1200


def test_a_timeout_gives_a_message_saying_what_to_tune(monkeypatch):
    def slow(*args, **kwargs):
        raise ollama_client.requests.exceptions.ReadTimeout()

    monkeypatch.setattr(ollama_client.requests, "post", slow)
    with pytest.raises(ollama_client.OllamaError, match="request_timeout"):
        list(stream_chat_messages("http://h", "m", []))
