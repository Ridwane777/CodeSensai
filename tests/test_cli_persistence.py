"""
Tests the [M1] Definition of Done end to end, on the real CLI:
"closing and reopening the CLI keeps the history and preferences".

Ollama is not called: `stream_chat` is replaced by a fake model that
records the messages it receives. That is what lets us check what the model
*sees* on the second launch, not just what is written to the database.

`test_failed_turn_is_not_saved` protects the Base Loop error handling:
it fails if the session is saved before the full answer is received.
"""
import builtins
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from sensai import cli
from sensai.core.ollama_client import OllamaError
from sensai.knowledge.memory import SESSIONS_FILE, SessionStore


@pytest.fixture
def lancer(tmp_path, monkeypatch):
    """Return a function that runs the CLI with a list of keyboard inputs.

    It returns the message lists sent to the model, one per turn.
    """
    projet = tmp_path / "projet"
    projet.mkdir()
    monkeypatch.chdir(projet)

    def _lancer(entrees, *, reponse="Got it.", echec=False, **options):
        settings = {
            "model": "fake-model",
            "host": "http://localhost:11434",
            "system_prompt": "You are CodeSensai.",
            "session": None,
            "new_session": False,
            "data_dir": str(tmp_path / "donnees"),
            "memory_prompt": "RESUME_INSTRUCTION",
            "retention_days": 30,
            # RAG off: these tests cover M1 and must not call Ollama.
            "rag": False,
            "rag_model": "bge-m3",
            "rag_min_score": 0.5,
            "rag_top_k": 5,
        }
        settings.update(options)
        envoyes = []

        def faux_stream_chat(host, model, messages):
            envoyes.append([dict(m) for m in messages])
            if echec:
                raise OllamaError("Ollama unreachable")
            yield reponse

        restantes = iter(entrees)

        def faux_input(_prompt=""):
            try:
                return next(restantes)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        monkeypatch.setattr(cli, "stream_chat", faux_stream_chat)
        monkeypatch.setattr(builtins, "input", faux_input)
        cli.main()
        return envoyes

    return _lancer


def test_history_kept_after_restart(lancer, capsys):
    lancer(["The login test fails"], reponse="Show me the traceback.")

    envoyes = lancer(["Do you remember the bug?"])

    messages = envoyes[0]
    assert {"role": "user", "content": "The login test fails"} in messages
    assert {"role": "assistant", "content": "Show me the traceback."} in messages
    assert "2 messages" in capsys.readouterr().out


def test_resume_instruction_only_for_resumed_session(lancer):
    """Real trial run (qwen3-coder:30b): on a resumed session, the model said
    "I cannot remember" while quoting the bug from the previous session.
    The instruction tells it the history is real; it only makes sense, and is
    only sent, when a session was resumed."""
    premier = lancer(["The login test fails"])
    assert "RESUME_INSTRUCTION" not in premier[0][0]["content"], "new session"

    reprise = lancer(["Do you remember the bug?"])
    assert "RESUME_INSTRUCTION" in reprise[0][0]["content"]

    nouvelle = lancer(["Hello"], new_session=True)
    assert "RESUME_INSTRUCTION" not in nouvelle[0][0]["content"]


def test_preference_kept_after_restart(lancer):
    lancer(["/remember use pytest"])

    envoyes = lancer(["Write a test"], new_session=True)

    systeme = envoyes[0][0]
    assert systeme["role"] == "system"
    assert "use pytest" in systeme["content"]


def test_new_session_does_not_carry_history(lancer):
    lancer(["The login test fails"])

    envoyes = lancer(["Hello"], new_session=True)

    assert [m["role"] for m in envoyes[0]] == ["system", "user"]


def test_failed_turn_is_not_saved(lancer):
    lancer(["Question that fails"], echec=True)

    envoyes = lancer(["Hello"])

    contenus = [m["content"] for m in envoyes[0]]
    assert "Question that fails" not in contenus


def test_unreadable_profile_does_not_block_startup(lancer, tmp_path, capsys):
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    (donnees / "profile.json").write_text("{ not json", encoding="utf-8")

    envoyes = lancer(["Hello"])

    assert envoyes, "the CLI must answer despite the unreadable profile"
    assert "profil" in capsys.readouterr().out.lower()


def test_corrupt_database_does_not_block_startup(lancer, tmp_path, capsys):
    """The database is neither overwritten nor deleted: it may hold
    recoverable conversations. The CLI starts without history."""
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    base = donnees / "sessions.db"
    base.write_bytes(b"this is not a SQLite database" * 100)

    envoyes = lancer(["Hello"])

    assert envoyes, "the CLI must answer despite the corrupt database"
    assert "sessions.db" in capsys.readouterr().out
    assert base.read_bytes() == b"this is not a SQLite database" * 100


def test_save_failure_does_not_stop_the_conversation(lancer, monkeypatch, capsys):
    """Disk full: warn, but the conversation goes on."""
    import sqlite3

    from sensai.knowledge.memory import SessionStore

    def save_impossible(self, session_id, turns):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(SessionStore, "save", save_impossible)

    envoyes = lancer(["First message", "Second message"])

    assert len(envoyes) == 2, "the second turn must have happened"
    assert {"role": "user", "content": "First message"} in envoyes[1]
    assert "disk is full" in capsys.readouterr().out


def test_unknown_session_does_not_crash(lancer, capsys):
    lancer([], session="nexiste-pas")

    sortie = capsys.readouterr().out
    assert "nexiste-pas" in sortie
    assert "purged" in sortie, "the user must understand why it may have disappeared"


def _vieillir_tout(tmp_path, jours):
    date = (datetime.now(UTC) - timedelta(days=jours)).isoformat()
    with sqlite3.connect(tmp_path / "donnees" / "sessions.db") as conn:
        conn.execute("UPDATE sessions SET updated_at = ?", (date,))


def test_startup_purge_is_announced(lancer, tmp_path, capsys):
    lancer(["Old forgotten bug"])
    _vieillir_tout(tmp_path, 31)
    capsys.readouterr()

    envoyes = lancer(["Hello"])

    sortie = capsys.readouterr().out
    assert "1 session" in sortie and "30 days" in sortie
    assert [m["role"] for m in envoyes[0]] == ["system", "user"], "nothing must be resumed"


def test_zero_retention_keeps_everything(lancer, tmp_path):
    lancer(["Old forgotten bug"])
    _vieillir_tout(tmp_path, 400)

    envoyes = lancer(["Do you remember?"], retention_days=0)

    assert {"role": "user", "content": "Old forgotten bug"} in envoyes[0]


def test_prompt_versions_shown_at_startup(lancer, capsys):
    """A4 (ADR-0010): know which prompt produced the answers."""
    lancer([], prompt_versions={"system": "v3", "memory": "v1"})

    assert "prompts : system v3, memory v1" in capsys.readouterr().out


def test_without_registry_no_versions_line(lancer, capsys):
    lancer([])

    assert "prompts :" not in capsys.readouterr().out


def test_secret_pasted_in_chat_is_saved_masked(lancer, tmp_path):
    """Issue #66: a secret pasted in the chat does not end up in clear text in
    sessions.db, nor in what is sent to the model (EV2 input filter, ADR-0027)."""
    envoyes = lancer(['My key is API_KEY="sk-abcdef1234567890abcdef", why does it fail?'])

    assert "sk-abcdef1234567890abcdef" not in str(envoyes)
    store = SessionStore(tmp_path / "donnees" / SESSIONS_FILE)
    contenu = str(store.load(store.list()[0].id))
    assert "sk-abcdef1234567890abcdef" not in contenu
    assert "REDACTED" in contenu
