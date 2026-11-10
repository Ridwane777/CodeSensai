"""
Tests M2 (token budget, rolling summary) end to end on the real CLI,
without Ollama.

Same pattern as `tests/test_cli_rag.py`: a fake `stream_chat` records the
messages received by the chat loop; `compression.stream_chat_messages` is
replaced too, for the summary.
"""
import builtins

import pytest

from sensai import cli
from sensai.knowledge import compression
from sensai.knowledge.memory import SESSIONS_FILE, SessionStore
from tests.test_cli_rag import lancer as lancer_avec_rag  # noqa: F401  (fixture)
from tests.test_cli_rag import projet  # noqa: F401  (fixture)


@pytest.fixture
def lancer(tmp_path, monkeypatch):
    def _lancer(entrees, *, resume="automatic summary", **options):
        settings = {
            "model": "fake-model",
            "host": "http://localhost:11434",
            "system_prompt": "You are CodeSensai.",
            "session": None,
            "new_session": False,
            "data_dir": str(tmp_path / "donnees"),
            "retention_days": 30,
            "rag": False,
            "rag_min_score": 0.0,
        }
        settings.update(options)
        envoyes = []
        options_recus = []

        def faux_stream_chat(host, model, messages):
            envoyes.append([dict(m) for m in messages])
            yield "Got it."

        def faux_stream_chat_messages(host, model, messages, options=None):
            options_recus.append(options)
            yield {"content": resume}

        restantes = iter(entrees)

        def faux_input(_prompt=""):
            try:
                return next(restantes)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        monkeypatch.setattr(cli, "stream_chat", faux_stream_chat)
        monkeypatch.setattr(compression, "stream_chat_messages", faux_stream_chat_messages)
        monkeypatch.setattr(builtins, "input", faux_input)
        cli.main()
        _lancer.options_recus = options_recus
        return envoyes

    return _lancer


def test_under_budget_full_history_is_sent(lancer):
    envoyes = lancer(["first question", "second question"])

    # Second turn: system + 2 previous turns + the new question.
    assert len(envoyes[1]) == 4
    assert envoyes[1][1]["content"] == "first question"


def test_over_budget_old_turns_are_summarized(lancer):
    questions = [f"question number {i} with a bit of text to add weight" for i in range(10)]
    envoyes = lancer(questions, token_budget_max=50, token_budget_keep_recent=2,
                      resume="here is the summary of the previous exchanges")

    dernier = envoyes[-1]
    # system + summary + (keep_recent=2 older turns counted from the last
    # complete turn) + the current turn's question, not yet answered by the
    # assistant: at the very least the summary must replace the bulk.
    contenu = " ".join(m["content"] for m in dernier)
    assert "here is the summary of the previous exchanges" in contenu
    assert "question number 0" not in contenu  # the oldest one was summarized


def test_saved_history_stays_intact_despite_compression(lancer, tmp_path):
    questions = [f"question number {i} with a bit of text to add weight" for i in range(10)]
    lancer(questions, token_budget_max=50, token_budget_keep_recent=2)

    store = SessionStore(tmp_path / "donnees" / SESSIONS_FILE)
    turns = store.load(store.list()[0].id)
    # Nothing is summarized in storage: every question asked is stored in full.
    questions_sauvees = [t["content"] for t in turns if t["role"] == "user"]
    assert questions_sauvees == questions


def test_no_token_budget_disables_summary(lancer):
    questions = [f"question number {i} with a bit of text to add weight" for i in range(10)]
    envoyes = lancer(questions, token_budget=False, token_budget_max=50)

    contenu = " ".join(m["content"] for m in envoyes[-1])
    assert "question number 0" in contenu  # never summarized: the budget is disabled


def test_empty_summary_keeps_raw_turns(lancer, capsys):
    questions = [f"question number {i} with a bit of text to add weight" for i in range(10)]
    envoyes = lancer(questions, token_budget_max=50, token_budget_keep_recent=2, resume="")

    # resume="" raises CompressionError (empty summary): turns stay raw.
    contenu = " ".join(m["content"] for m in envoyes[-1])
    assert "question number 0" in contenu
    assert "automatic history summary failed" in capsys.readouterr().out


def test_num_ctx_is_passed_to_summary_call(lancer):
    """PR #97 review: without num_ctx, Ollama silently truncates before the
    budget gets a chance to act — it must be sent with the call."""
    questions = [f"question number {i} with a bit of text to add weight" for i in range(10)]
    lancer(
        questions, token_budget_max=50, token_budget_keep_recent=2, num_ctx=4096,
        resume="summary",
    )
    assert {"num_ctx": 4096} in lancer.options_recus


def test_rag_context_counts_in_budget(lancer_avec_rag, projet):  # noqa: F811
    """PR #97 review: compression must apply AFTER the RAG context is added
    to the question, otherwise the budget ignores what is really sent."""
    resume_vu = []

    def faux_stream_chat_messages(host, model, messages, options=None):
        resume_vu.append(True)
        yield {"content": "summary of the exchanges"}

    import sensai.knowledge.compression as compression_module
    original = compression_module.stream_chat_messages
    try:
        compression_module.stream_chat_messages = faux_stream_chat_messages
        # A short, repeated question: alone it would stay under a small
        # budget; with the RAG passage added (src/auth.py), it exceeds it.
        questions = [f"q{i}" for i in range(8)]
        _envoyes, _ = lancer_avec_rag(
            questions, token_budget=True, token_budget_max=80, token_budget_keep_recent=2,
        )
        assert resume_vu, "the budget must kick in once the RAG context is added"
    finally:
        compression_module.stream_chat_messages = original


# --- num_ctx on every path to Ollama (PR #97 review) ----------------------------


def test_subagents_get_num_ctx(lancer, monkeypatch):
    """`delegate_task` / `team_task` were still subject to Ollama's default
    truncation while the main loop sent `num_ctx`."""
    from sensai.core.events import Done, Token
    from sensai.tools import delegate_tool

    recus = []

    def faux_tour(host, model, messages, tools, num_ctx=None):
        recus.append(num_ctx)
        yield Token(text="ok")
        yield Done()

    instances = []

    class DelegateEspion(cli.DelegateTool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(delegate_tool, "_run_agent_turn", faux_tour)
    monkeypatch.setattr(cli, "DelegateTool", DelegateEspion)
    lancer(["Hello"], num_ctx=4096)

    instances[0].delegate("a subtask")

    assert recus == [4096]


def test_structured_gets_num_ctx(lancer, monkeypatch):
    vus = []

    def espion(line, **kwargs):
        vus.append(kwargs.get("num_ctx"))
        return "{}" if line.startswith("/structured") else None

    monkeypatch.setattr(cli, "handle_structured_command", espion)
    lancer(["/structured schema.json do X"], num_ctx=4096)
    assert vus == [4096]


def test_model_preload_sends_num_ctx(monkeypatch):
    """Ollama reloads the model if a request's window differs from the one used
    at load time: we warm it up with the same one."""
    envoyes = []

    class Reponse:
        def raise_for_status(self):
            pass

    def faux_post(url, json=None, timeout=None):
        envoyes.append((url, json))
        return Reponse()

    monkeypatch.setattr(cli.requests, "post", faux_post)
    cli.preload_model("http://h", "m", num_ctx=4096)
    cli.preload_model("http://h", "m")

    assert envoyes[0][1] == {"model": "m", "prompt": "", "options": {"num_ctx": 4096}}
    assert envoyes[1][1] == {"model": "m", "prompt": ""}


def test_message_too_big_to_summarize_warns(lancer, capsys):
    """PR #97 review: nothing to summarize, the message is sent as is — but the
    user must be told, not find out from an answer built on a truncated context."""
    envoyes = lancer(["x" * 5000], token_budget_max=50)

    assert envoyes[0][-1]["content"] == "x" * 5000  # sent as is
    assert "exceeds the token" in capsys.readouterr().out


def test_rag_alone_can_exceed_budget_and_warns(lancer_avec_rag, projet, capsys):  # noqa: F811
    """A short question, but inflated by a passage from the project."""
    lancer_avec_rag(["token"], token_budget=True, token_budget_max=20)
    assert "exceeds the token" in capsys.readouterr().out


def test_under_budget_no_warning(lancer, capsys):
    lancer(["hello"], token_budget_max=5000)
    assert "exceeds the token" not in capsys.readouterr().out


def test_describe_context_shows_exact_prompt_and_settings():
    """/context shows the exact prompt sent (ADR-0058)."""
    from sensai.core.context_view import describe_context

    out = describe_context(
        [{"role": "system", "content": "You are CodeSensai."}, {"role": "user", "content": "hi"}],
        8192, 6192, {"temperature": 0.2, "top_p": 0.9})
    assert "2 message(s)" in out and "num_ctx=8192" in out and "budget=6192" in out
    assert "temperature=0.2, top_p=0.9" in out
    assert "--- [1] system" in out and "You are CodeSensai." in out and "hi" in out
