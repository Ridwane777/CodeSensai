"""The CLI also writes to the turn log [EV3] (same file as the web app)."""
from sensai.knowledge.memory import SESSIONS_FILE, SessionStore
from sensai.observability.journal import JOURNAL_FILE, Journal
from tests.test_cli_persistence import lancer  # noqa: F401 - shared fixture


def test_a_cli_turn_is_logged(lancer, tmp_path):  # noqa: F811
    lancer(["Hello"], reponse="Hi.")
    data = tmp_path / "donnees"
    [session] = [s for s in SessionStore(data / SESSIONS_FILE).list(str(tmp_path / "projet"))]
    [turn] = Journal(data / JOURNAL_FILE).turns(session.id)
    assert turn["interface"] == "cli" and turn["outcome"] == "final_answer"
    assert turn["model_ms"] is not None and turn["tokens_sent"] > 0
