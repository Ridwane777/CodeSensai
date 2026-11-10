"""
Tests the token budget and rolling-summary compression — feature
[M2], ADR-0045.

`stream_chat_messages` is replaced by a fake summarizer: no network call,
the test controls exactly what the model "answers".
"""
import pytest

from sensai.core.ollama_client import OllamaError
from sensai.knowledge import compression
from sensai.knowledge.compression import (
    CompressionError,
    budget_from_num_ctx,
    compress_messages,
    count_tokens,
    summarize,
)


def _turn(role, content):
    return {"role": role, "content": content}


def test_count_tokens_approximates_four_chars_per_token():
    assert count_tokens("a" * 40) == 10
    assert count_tokens("") == 1  # never zero: an empty text still counts


def test_budget_from_num_ctx_removes_the_answer_margin():
    assert budget_from_num_ctx(8000) == 8000 - compression.RESPONSE_MARGIN_TOKENS


def test_under_budget_nothing_changes():
    messages = [_turn("system", "instruction"), _turn("user", "short question")]
    resultat, compresse = compress_messages("host", "model", messages, max_tokens=1000)
    assert resultat == messages
    assert compresse is False


def test_few_turns_even_over_budget_trigger_nothing():
    # default keep_recent (6) >= number of turns: nothing to summarize.
    messages = [_turn("user", "x" * 100), _turn("assistant", "y" * 100)]
    resultat, compresse = compress_messages("host", "model", messages, max_tokens=1)
    assert resultat == messages
    assert compresse is False


def test_over_budget_summarizes_the_oldest(monkeypatch):
    def faux_stream(host, model, messages, options=None):
        yield {"content": "compact summary"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)

    anciens = [_turn("user" if i % 2 == 0 else "assistant", f"turn {i}" * 20) for i in range(10)]
    recents = [_turn("user", "recent question"), _turn("assistant", "recent answer")]
    messages = [_turn("system", "instruction"), *anciens, *recents]

    resultat, compresse = compress_messages(
        "host", "model", messages, max_tokens=1, keep_recent=2
    )
    assert compresse is True
    assert len(resultat) == 1 + len(recents)  # a single system message, then the recent turns
    assert resultat[0]["role"] == "system"
    assert "instruction" in resultat[0]["content"]
    assert "compact summary" in resultat[0]["content"]
    assert resultat[-2:] == recents


def test_user_assistant_alternation_kept_after_compression(monkeypatch):
    """PR #97 review: the summary is merged into the system message, never a
    second `user` message right before the first kept turn."""
    def faux_stream(host, model, messages, options=None):
        yield {"content": "summary"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)

    anciens = [_turn("user" if i % 2 == 0 else "assistant", "x" * 50) for i in range(8)]
    recents = [_turn("user", "a question"), _turn("assistant", "an answer")]
    messages = [_turn("system", "instruction"), *anciens, *recents]

    resultat, _ = compress_messages("host", "model", messages, max_tokens=1, keep_recent=2)
    roles = [m["role"] for m in resultat]
    assert roles == ["system", "user", "assistant"]


def test_single_message_bigger_than_budget_is_sent_silently(monkeypatch):
    """Nothing to summarize (a single turn, below keep_recent): the message is
    sent as is, even over budget — no infinite loop, no error."""
    def faux_stream(host, model, messages, options=None):
        pytest.fail("must never be called: nothing to summarize")

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)

    messages = [_turn("system", "instruction"), _turn("user", "x" * 1_000_000)]
    resultat, compresse = compress_messages(
        "host", "model", messages, max_tokens=1, keep_recent=6
    )
    assert resultat == messages
    assert compresse is False


def test_recent_turns_stay_intact_after_compression(monkeypatch):
    def faux_stream(host, model, messages, options=None):
        yield {"content": "summary"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)

    anciens = [_turn("user" if i % 2 == 0 else "assistant", "x" * 50) for i in range(8)]
    recents = [_turn("user", "a real, precise question")]
    messages = [*anciens, *recents]

    resultat, _ = compress_messages("host", "model", messages, max_tokens=1, keep_recent=1)
    assert resultat[-1] == _turn("user", "a real, precise question")


def test_ollama_unavailable_raises_compressionerror(monkeypatch):
    def faux_stream(host, model, messages, options=None):
        raise OllamaError("unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    with pytest.raises(CompressionError, match="unreachable"):
        summarize("host", "model", [_turn("user", "a"), _turn("assistant", "b")])


def test_empty_answer_raises_compressionerror(monkeypatch):
    def faux_stream(host, model, messages, options=None):
        yield {"content": ""}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    with pytest.raises(CompressionError, match="no summary"):
        summarize("host", "model", [_turn("user", "a")])


def test_summarize_passes_num_ctx_in_options(monkeypatch):
    recu = {}

    def faux_stream(host, model, messages, options=None):
        recu["options"] = options
        yield {"content": "summary"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    summarize("host", "model", [_turn("user", "a")], num_ctx=8192)
    assert recu["options"] == {"num_ctx": 8192}


def test_summarize_caps_input_to_num_ctx(monkeypatch):
    """PR #97 review: summarizing turns that are themselves too big for num_ctx
    must not be silently truncated by Ollama — we cap them ourselves."""
    recu = {}

    def faux_stream(host, model, messages, options=None):
        recu["transcript"] = messages[-1]["content"]
        yield {"content": "summary"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    enormes_tours = [_turn("user", "x" * 100_000)]
    summarize("host", "model", enormes_tours, num_ctx=1000)
    limite = budget_from_num_ctx(1000) * compression.CHARS_PER_TOKEN
    assert len(recu["transcript"]) <= limite + len("[…beginning truncated, too old "
                                                     "to fit in the context…]\n")


def test_resolve_budget_prefers_the_explicit_setting():
    assert compression.resolve_budget(100, 4096) == 100


def test_resolve_budget_derives_from_num_ctx_otherwise():
    assert compression.resolve_budget(None, 4096) == budget_from_num_ctx(4096)
    defaut = budget_from_num_ctx(compression.DEFAULT_NUM_CTX)
    assert compression.resolve_budget(None, None) == defaut


def test_compress_messages_without_explicit_budget_follows_num_ctx(monkeypatch):
    """A single default (PR #97 review): without `max_tokens`, the limit is
    `num_ctx` minus the margin — no more 8000 constant contradicting the rest."""
    def faux_stream(host, model, messages, options=None):
        yield {"content": "summary"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_stream)
    # tiny num_ctx: the derived budget is 1 token, everything overflows.
    messages = [_turn("user" if i % 2 == 0 else "assistant", "x" * 400) for i in range(10)]
    _, compresse = compress_messages("host", "model", messages, keep_recent=2, num_ctx=1)
    assert compresse is True
    # large num_ctx: the same history fits easily.
    _, compresse = compress_messages("host", "model", messages, keep_recent=2, num_ctx=32768)
    assert compresse is False
