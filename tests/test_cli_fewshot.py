"""
Tests A7 (automatic few-shot) end to end on the real CLI, without Ollama.

Same pattern as `tests/test_cli_rag.py`: a fake `stream_chat` records the
messages it receives, and `FakeEmbedder` (hashed bag of words) replaces the embeddings.
"""
import builtins

import pytest

from sensai import cli
from sensai.knowledge.rag import EmbeddingError
from tests.knowledge.test_rag import FakeEmbedder
from tests.test_cli_rag import lancer as lancer_avec_rag  # noqa: F401  (fixture)
from tests.test_cli_rag import projet  # noqa: F401  (fixture)


@pytest.fixture
def exemples(tmp_path):
    path = tmp_path / "exemples.jsonl"
    path.write_text(
        '{"id": "1", "question": "Explain the verifier_token function",'
        ' "answer": "It compares the received token with the expected secret."}\n',
        encoding="utf-8",
    )
    return path


@pytest.fixture
def lancer(tmp_path, monkeypatch):
    def _lancer(entrees, *, embedder=None, **options):
        settings = {
            "model": "fake-model",
            "host": "http://localhost:11434",
            "system_prompt": "You are CodeSensai.",
            "session": None,
            "new_session": False,
            "data_dir": str(tmp_path / "donnees"),
            "retention_days": 30,
            "rag": False,
            "rag_model": "bge-m3",
            "rag_min_score": 0.0,
            "fewshot_min_score": 0.1,
        }
        settings.update(options)
        embedder = embedder or FakeEmbedder()
        envoyes = []

        def faux_stream_chat(host, model, messages):
            envoyes.append([dict(m) for m in messages])
            yield "Got it."

        restantes = iter(entrees)

        def faux_input(_prompt=""):
            try:
                return next(restantes)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        monkeypatch.setattr(cli, "stream_chat", faux_stream_chat)
        monkeypatch.setattr(cli, "OllamaEmbedder", lambda host, model: embedder)
        monkeypatch.setattr(builtins, "input", faux_input)
        cli.main()
        return envoyes

    return _lancer


def test_close_question_gets_the_example(lancer, exemples):
    envoyes = lancer(
        ["How does the verifier_token function work?"],
        fewshot_examples=str(exemples),
    )
    question = envoyes[0][-1]["content"]
    assert "It compares the received token with the expected secret" in question
    assert "How does the verifier_token function work?" in question


def test_unrelated_question_gets_nothing(lancer, exemples):
    envoyes = lancer(
        ["A question unrelated to the examples"],
        fewshot_examples=str(exemples), fewshot_min_score=0.99,
    )
    question = envoyes[0][-1]["content"]
    assert "It compares the received token with the expected secret" not in question


def test_no_configured_file_adds_nothing(lancer):
    envoyes = lancer(["Hello"])
    assert envoyes[0][-1]["content"] == "Hello"


def test_missing_file_does_not_prevent_conversation(lancer, tmp_path, capsys):
    envoyes = lancer(["Hello"], fewshot_examples=str(tmp_path / "absent.jsonl"))
    assert envoyes[0][-1]["content"] == "Hello"
    assert "few-shot" in capsys.readouterr().out


def test_secret_in_an_example_is_masked(lancer, tmp_path):
    """PR #96 review: the examples file may come from a real session, with a
    secret in the recorded answer - it must never reach the model in clear
    text, as with RAG passages (EV2)."""
    path = tmp_path / "exemples_secret.jsonl"
    path.write_text(
        '{"id": "1", "question": "Explain the verifier_token function",'
        ' "answer": "Use ghp_abcdefghijklmnopqrstuvwxyz0123456789 to authenticate."}\n',
        encoding="utf-8",
    )
    envoyes = lancer(
        ["How does the verifier_token function work?"],
        fewshot_examples=str(path), fewshot_min_score=0.1,
    )
    question = envoyes[0][-1]["content"]
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in question
    assert "REDACTED" in question


def test_rag_and_fewshot_coexist_in_the_same_message(lancer_avec_rag, exemples):  # noqa: F811
    """PR #96 review: both blocks can be added to the same question without
    stepping on each other (ADR-0044)."""
    envoyes, _ = lancer_avec_rag(
        ["How does the verifier_token function work?"],
        fewshot_examples=str(exemples), fewshot_min_score=0.1,
    )
    question = envoyes[0][-1]["content"]
    assert "It compares the received token with the expected secret" in question  # the few-shot
    assert "src/auth.py" in question  # the RAG


def test_losing_ollama_mid_session_disables_fewshot(lancer, exemples, capsys):
    """PR #96 review: if Ollama goes down after the initial load, few-shot is
    disabled from then on instead of crashing the turn."""

    class EmbedderInstable:
        def __init__(self):
            self.appels = 0

        def __call__(self, textes):
            self.appels += 1
            if self.appels == 1:
                return FakeEmbedder()(textes)  # the initial load succeeds
            raise EmbeddingError("unreachable")  # no question can match anymore

    envoyes = lancer(
        ["first question", "second question"],
        fewshot_examples=str(exemples), embedder=EmbedderInstable(),
    )
    assert len(envoyes) == 2, "the session goes on despite the outage"
    assert "second question" == envoyes[1][-1]["content"]
