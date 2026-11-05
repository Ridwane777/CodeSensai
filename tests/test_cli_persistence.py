"""
Teste la Definition of Done de [M1] de bout en bout, sur le vrai CLI :
« fermer et rouvrir le CLI conserve l'historique et les préférences ».

Ollama n'est pas appelé : `stream_chat` est remplacé par un faux modèle qui
note les messages reçus. C'est ce qui permet de vérifier ce que le modèle
*voit* au second lancement, pas seulement ce qui est écrit en base.

`test_tour_en_echec_non_sauvegarde` protège la gestion d'erreurs du Base
Loop : il échoue si on sauvegarde la session avant d'avoir la réponse complète.
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
    """Retourne une fonction qui lance le CLI avec une liste d'entrées clavier.

    Renvoie les listes de messages envoyées au modèle, une par tour.
    """
    projet = tmp_path / "projet"
    projet.mkdir()
    monkeypatch.chdir(projet)

    def _lancer(entrees, *, reponse="D'accord.", echec=False, **options):
        settings = {
            "model": "faux-modele",
            "host": "http://localhost:11434",
            "system_prompt": "Tu es CodeSensei.",
            "session": None,
            "new_session": False,
            "data_dir": str(tmp_path / "donnees"),
            "memory_prompt": "CONSIGNE_DE_REPRISE",
            "retention_days": 30,
            # RAG coupé : ces tests portent sur M1 et ne doivent pas appeler Ollama.
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
                raise OllamaError("Ollama injoignable")
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


def test_historique_conserve_apres_relance(lancer, capsys):
    lancer(["Le test de login échoue"], reponse="Montre-moi la trace.")

    envoyes = lancer(["Tu te souviens du bug ?"])

    messages = envoyes[0]
    assert {"role": "user", "content": "Le test de login échoue"} in messages
    assert {"role": "assistant", "content": "Montre-moi la trace."} in messages
    assert "2 messages" in capsys.readouterr().out


def test_consigne_de_reprise_seulement_si_session_reprise(lancer):
    """Essai réel (qwen3-coder:30b) : sur une session reprise, le modèle disait
    « je ne peux pas me souvenir » tout en citant le bug de la session précédente.
    La consigne lui dit que l'historique est réel ; elle n'a de sens, et n'est
    envoyée, que si une session a été reprise."""
    premier = lancer(["Le test de login échoue"])
    assert "CONSIGNE_DE_REPRISE" not in premier[0][0]["content"], "nouvelle session"

    reprise = lancer(["Tu te souviens du bug ?"])
    assert "CONSIGNE_DE_REPRISE" in reprise[0][0]["content"]

    nouvelle = lancer(["Bonjour"], new_session=True)
    assert "CONSIGNE_DE_REPRISE" not in nouvelle[0][0]["content"]


def test_preference_conservee_apres_relance(lancer):
    lancer(["/remember utilise pytest"])

    envoyes = lancer(["Écris un test"], new_session=True)

    systeme = envoyes[0][0]
    assert systeme["role"] == "system"
    assert "utilise pytest" in systeme["content"]


def test_nouvelle_session_n_emporte_pas_l_historique(lancer):
    lancer(["Le test de login échoue"])

    envoyes = lancer(["Bonjour"], new_session=True)

    assert [m["role"] for m in envoyes[0]] == ["system", "user"]


def test_tour_en_echec_non_sauvegarde(lancer):
    lancer(["Question qui échoue"], echec=True)

    envoyes = lancer(["Bonjour"])

    contenus = [m["content"] for m in envoyes[0]]
    assert "Question qui échoue" not in contenus


def test_profil_illisible_ne_bloque_pas_le_demarrage(lancer, tmp_path, capsys):
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    (donnees / "profile.json").write_text("{ pas du json", encoding="utf-8")

    envoyes = lancer(["Bonjour"])

    assert envoyes, "le CLI doit avoir répondu malgré le profil illisible"
    assert "profil" in capsys.readouterr().out.lower()


def test_base_corrompue_ne_bloque_pas_le_demarrage(lancer, tmp_path, capsys):
    """La base n'est ni écrasée ni supprimée : elle contient peut-être des
    conversations récupérables. Le CLI démarre sans historique."""
    donnees = tmp_path / "donnees"
    donnees.mkdir()
    base = donnees / "sessions.db"
    base.write_bytes(b"ceci n'est pas une base SQLite" * 100)

    envoyes = lancer(["Bonjour"])

    assert envoyes, "le CLI doit avoir répondu malgré la base corrompue"
    assert "sessions.db" in capsys.readouterr().out
    assert base.read_bytes() == b"ceci n'est pas une base SQLite" * 100


def test_echec_de_sauvegarde_ne_coupe_pas_la_conversation(lancer, monkeypatch, capsys):
    """Disque plein : on prévient, mais la conversation continue."""
    import sqlite3

    from sensai.knowledge.memory import SessionStore

    def save_impossible(self, session_id, turns):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(SessionStore, "save", save_impossible)

    envoyes = lancer(["Premier message", "Second message"])

    assert len(envoyes) == 2, "le second tour doit avoir eu lieu"
    assert {"role": "user", "content": "Premier message"} in envoyes[1]
    assert "disk is full" in capsys.readouterr().out


def test_session_inconnue_ne_plante_pas(lancer, capsys):
    lancer([], session="nexiste-pas")

    sortie = capsys.readouterr().out
    assert "nexiste-pas" in sortie
    assert "purgée" in sortie, "l'utilisateur doit comprendre pourquoi elle a pu disparaître"


def _vieillir_tout(tmp_path, jours):
    date = (datetime.now(UTC) - timedelta(days=jours)).isoformat()
    with sqlite3.connect(tmp_path / "donnees" / "sessions.db") as conn:
        conn.execute("UPDATE sessions SET updated_at = ?", (date,))


def test_purge_au_demarrage_est_annoncee(lancer, tmp_path, capsys):
    lancer(["Vieux bug oublié"])
    _vieillir_tout(tmp_path, 31)
    capsys.readouterr()

    envoyes = lancer(["Bonjour"])

    sortie = capsys.readouterr().out
    assert "1 session" in sortie and "30 jours" in sortie
    assert [m["role"] for m in envoyes[0]] == ["system", "user"], "rien ne doit être repris"


def test_retention_zero_garde_tout(lancer, tmp_path):
    lancer(["Vieux bug oublié"])
    _vieillir_tout(tmp_path, 400)

    envoyes = lancer(["Tu te souviens ?"], retention_days=0)

    assert {"role": "user", "content": "Vieux bug oublié"} in envoyes[0]


def test_versions_de_prompts_affichees_au_lancement(lancer, capsys):
    """A4 (ADR-0010) : savoir avec quel prompt les réponses sont produites."""
    lancer([], prompt_versions={"system": "v3", "memory": "v1"})

    assert "prompts : system v3, memory v1" in capsys.readouterr().out


def test_sans_registre_aucune_ligne_de_versions(lancer, capsys):
    lancer([])

    assert "prompts :" not in capsys.readouterr().out


def test_secret_colle_dans_le_chat_enregistre_masque(lancer, tmp_path):
    """Issue #66 : un secret collé dans le chat ne finit pas en clair dans
    sessions.db, ni dans ce qui part au modèle (filtre d'entrée EV2, ADR-0027)."""
    envoyes = lancer(['Ma clé est API_KEY="sk-abcdef1234567890abcdef", pourquoi ça échoue ?'])

    assert "sk-abcdef1234567890abcdef" not in str(envoyes)
    store = SessionStore(tmp_path / "donnees" / SESSIONS_FILE)
    contenu = str(store.load(store.list()[0].id))
    assert "sk-abcdef1234567890abcdef" not in contenu
    assert "REDACTED" in contenu
