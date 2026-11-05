"""
Teste A7 (few-shot automatique) de bout en bout sur le vrai CLI, sans Ollama.

Même patron que `tests/test_cli_rag.py` : un faux `stream_chat` note les
messages reçus, et `FauxEmbedder` (sac de mots haché) remplace les embeddings.
"""
import builtins

import pytest

from sensai import cli
from sensai.knowledge.rag import EmbeddingError
from tests.knowledge.test_rag import FauxEmbedder
from tests.test_cli_rag import lancer as lancer_avec_rag  # noqa: F401  (fixture)
from tests.test_cli_rag import projet  # noqa: F401  (fixture)


@pytest.fixture
def exemples(tmp_path):
    path = tmp_path / "exemples.jsonl"
    path.write_text(
        '{"id": "1", "question": "Explique la fonction verifier_token",'
        ' "answer": "Elle compare le jeton reçu au secret attendu."}\n',
        encoding="utf-8",
    )
    return path


@pytest.fixture
def lancer(tmp_path, monkeypatch):
    def _lancer(entrees, *, embedder=None, **options):
        settings = {
            "model": "faux-modele",
            "host": "http://localhost:11434",
            "system_prompt": "Tu es CodeSensei.",
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
        embedder = embedder or FauxEmbedder()
        envoyes = []

        def faux_stream_chat(host, model, messages):
            envoyes.append([dict(m) for m in messages])
            yield "D'accord."

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


def test_question_proche_recoit_lexemple(lancer, exemples):
    envoyes = lancer(
        ["Comment marche la fonction verifier_token ?"],
        fewshot_examples=str(exemples),
    )
    question = envoyes[0][-1]["content"]
    assert "Elle compare le jeton reçu au secret attendu" in question
    assert "Comment marche la fonction verifier_token ?" in question


def test_question_sans_rapport_ne_recoit_rien(lancer, exemples):
    envoyes = lancer(
        ["Une question sans aucun rapport avec les exemples"],
        fewshot_examples=str(exemples), fewshot_min_score=0.99,
    )
    question = envoyes[0][-1]["content"]
    assert "Elle compare le jeton reçu au secret attendu" not in question


def test_sans_fichier_configure_rien_n_est_ajoute(lancer):
    envoyes = lancer(["Bonjour"])
    assert envoyes[0][-1]["content"] == "Bonjour"


def test_fichier_introuvable_n_empeche_pas_la_conversation(lancer, tmp_path, capsys):
    envoyes = lancer(["Bonjour"], fewshot_examples=str(tmp_path / "absent.jsonl"))
    assert envoyes[0][-1]["content"] == "Bonjour"
    assert "few-shot" in capsys.readouterr().out


def test_secret_dans_un_exemple_est_masque(lancer, tmp_path):
    """Revue PR #96 : le fichier d'exemples peut venir d'une vraie session,
    avec un secret dans la réponse enregistrée — il ne doit jamais partir en
    clair au modèle, comme pour les passages du RAG (EV2)."""
    path = tmp_path / "exemples_secret.jsonl"
    path.write_text(
        '{"id": "1", "question": "Explique la fonction verifier_token",'
        ' "answer": "Utilise ghp_abcdefghijklmnopqrstuvwxyz0123456789 pour authentifier."}\n',
        encoding="utf-8",
    )
    envoyes = lancer(
        ["Comment marche la fonction verifier_token ?"],
        fewshot_examples=str(path), fewshot_min_score=0.1,
    )
    question = envoyes[0][-1]["content"]
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in question
    assert "REDACTED" in question


def test_rag_et_fewshot_coexistent_dans_le_meme_message(lancer_avec_rag, exemples):  # noqa: F811
    """Revue PR #96 : les deux blocs peuvent s'ajouter à la même question
    sans se piétiner (ADR-0044)."""
    envoyes, _ = lancer_avec_rag(
        ["Comment marche la fonction verifier_token ?"],
        fewshot_examples=str(exemples), fewshot_min_score=0.1,
    )
    question = envoyes[0][-1]["content"]
    assert "Elle compare le jeton reçu au secret attendu" in question  # le few-shot
    assert "src/auth.py" in question  # le RAG


def test_perte_d_ollama_en_cours_de_session_desactive_le_fewshot(lancer, exemples, capsys):
    """Revue PR #96 : si Ollama tombe après le chargement initial, le
    few-shot se désactive pour la suite au lieu de planter le tour."""

    class EmbedderInstable:
        def __init__(self):
            self.appels = 0

        def __call__(self, textes):
            self.appels += 1
            if self.appels == 1:
                return FauxEmbedder()(textes)  # le chargement initial réussit
            raise EmbeddingError("injoignable")  # plus aucune question ne peut matcher

    envoyes = lancer(
        ["première question", "deuxième question"],
        fewshot_examples=str(exemples), embedder=EmbedderInstable(),
    )
    assert len(envoyes) == 2, "la session continue malgré la panne"
    assert "deuxième question" == envoyes[1][-1]["content"]
