"""
The token budget (M2, ADR-0045) and `num_ctx` in the web server.

The CLI had them, the web did not (PR #97 review): a feature enabled by default
on one side and missing on the other contradicted ADR-0035 ("the same agent on both
sides"). Here `WebRuntime` is tested directly, without an HTTP server or Ollama.
"""
import threading

import pytest

pytest.importorskip("fastapi")

from sensai.core.events import Done, Token
from sensai.core.ollama_client import OllamaError
from sensai.knowledge import compression
from sensai.tools import delegate_tool
from sensai.web import runtime as runtime_module
from sensai.web.runtime import WebRuntime
from tests.knowledge.test_rag import FauxEmbedder


class FakeTurn:
    """Replaces the agent loop: records the received messages and answers "ok"."""

    def __init__(self):
        self.messages = []

    def __call__(self, host, model, messages, tools):
        self.messages.append([dict(m) for m in messages])
        yield Token("ok")
        yield Done("final_answer")


@pytest.fixture
def factory(tmp_path):
    def _factory(**options):
        project = tmp_path / "project"
        project.mkdir(exist_ok=True)
        settings = {
            "model": "fake-model",
            "host": "http://127.0.0.1:1",
            "system_prompt": "You are CodeSensai.",
            "memory_prompt": "Conversation resumed.",
            "data_dir": str(tmp_path / "data"),
            "retention_days": 30,
            "rag": False,
            "rag_model": "bge-m3",
            "rag_min_score": 0.0,
            "rag_top_k": 3,
            "rag_rerank": False,
            "cache": False,
        }
        settings.update(options)
        turn = FakeTurn()
        runtime = WebRuntime(settings, project, run_turn=turn,
                             embedder_factory=lambda host, model: FauxEmbedder(),
                             converter_factory=lambda: None, reranker_factory=None)
        return runtime, turn

    return _factory


def play(runtime, turns, text):
    events = []
    new_turns = runtime.run_turn(turns, text, events.append, threading.Event(),
                                 lambda request: True)
    return new_turns, events


def history(n_pairs):
    turns = []
    for i in range(n_pairs):
        turns += [{"role": "user", "content": f"question number {i} with a bit of text"},
                  {"role": "assistant", "content": f"answer number {i} with a bit of text"}]
    return turns


def test_num_ctx_is_sent_with_the_default_agent_loop(tmp_path, monkeypatch):
    seen = []

    def fake_agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
        seen.append(num_ctx)
        yield Token("ok")
        yield Done("final_answer")

    monkeypatch.setattr(runtime_module, "run_agent_turn", fake_agent)
    project = tmp_path / "project"
    project.mkdir()
    runtime = WebRuntime(
        {"model": "m", "host": "http://h", "rag": False, "rag_model": "bge-m3",
         "rag_min_score": 0.0, "data_dir": str(tmp_path / "d"), "retention_days": 30,
         "num_ctx": 4096},
        project, embedder_factory=lambda host, model: FauxEmbedder(),
        converter_factory=lambda: None, reranker_factory=None)

    play(runtime, [], "Hello")

    assert seen == [4096]


def test_web_subagents_receive_num_ctx(factory, monkeypatch):
    seen = []

    def fake_agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
        seen.append(num_ctx)
        yield Token("ok")
        yield Done("final_answer")

    monkeypatch.setattr(delegate_tool, "_run_agent_turn", fake_agent)
    runtime, _ = factory(num_ctx=4096)

    gateway = runtime.make_gateway(lambda request: True)
    gateway.registry.get("delegate_task").delegate("a subtask")

    assert seen == [4096]


def test_over_the_budget_old_turns_are_summarized(factory, monkeypatch):
    calls = []

    def fake_summary(host, model, messages, options=None):
        calls.append(options)
        yield {"content": "here is the summary"}

    monkeypatch.setattr(compression, "stream_chat_messages", fake_summary)
    runtime, turn = factory(token_budget_max=50, token_budget_keep_recent=2, num_ctx=4096)
    turns = history(10)

    new_turns, _ = play(runtime, turns, "a new question")

    sent = turn.messages[0]
    assert "here is the summary" in sent[0]["content"]
    assert len(sent) < len(turns)  # old turns are no longer sent
    assert calls == [{"num_ctx": 4096}]  # the summary call itself sends num_ctx
    # The saved session (M1) keeps everything, intact.
    assert new_turns[:len(turns)] == turns
    assert new_turns[-2]["content"] == "a new question"


def test_disabled_token_budget_summarizes_nothing(factory, monkeypatch):
    monkeypatch.setattr(compression, "stream_chat_messages",
                        lambda *a, **k: pytest.fail("must not summarize"))
    runtime, turn = factory(token_budget=False, token_budget_max=50)
    turns = history(10)

    play(runtime, turns, "a new question")

    assert len(turn.messages[0]) == 1 + len(turns) + 1


def test_summary_failure_keeps_history_and_warns_once(factory, monkeypatch):
    def broken(host, model, messages, options=None):
        raise OllamaError("unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(compression, "stream_chat_messages", broken)
    runtime, turn = factory(token_budget_max=50, token_budget_keep_recent=2)
    turns = history(10)

    play(runtime, turns, "first")
    play(runtime, turns, "second")

    assert len(turn.messages[0]) == 1 + len(turns) + 1  # nothing is lost
    warnings = [n for n in runtime.notices if "Automatic history summary" in n]
    assert len(warnings) == 1  # not repeated on every turn


def test_a_context_too_large_to_reduce_warns(factory, monkeypatch):
    """PR #97 review: a last message that alone exceeds the budget is sent
    as is; at least the user is warned the window may be truncated."""
    monkeypatch.setattr(compression, "stream_chat_messages",
                        lambda *a, **k: pytest.fail("nothing to summarize"))
    runtime, turn = factory(token_budget_max=50)

    play(runtime, [], "x" * 5000)

    assert any("exceeds the token budget" in n for n in runtime.notices)
    assert turn.messages[0][-1]["content"] == "x" * 5000  # sent as is
