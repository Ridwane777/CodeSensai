"""Le CLI écrit aussi dans le journal des tours [EV3] (même fichier que le web)."""
from sensai.knowledge.memory import SESSIONS_FILE, SessionStore
from sensai.observability.journal import JOURNAL_FILE, Journal
from tests.test_cli_persistence import lancer  # noqa: F401 — fixture partagée


def test_un_tour_du_cli_est_journalise(lancer, tmp_path):  # noqa: F811
    lancer(["Bonjour"], reponse="Salut.")
    data = tmp_path / "donnees"
    [session] = [s for s in SessionStore(data / SESSIONS_FILE).list(str(tmp_path / "projet"))]
    [turn] = Journal(data / JOURNAL_FILE).turns(session.id)
    assert turn["interface"] == "cli" and turn["outcome"] == "final_answer"
    assert turn["model_ms"] is not None and turn["tokens_sent"] > 0
