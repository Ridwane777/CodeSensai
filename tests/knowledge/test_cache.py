"""
Tests du cache sémantique — feature [A6].

Chaque bloc renvoie à une user story de docs/user-stories/A6-semantic-cache.md ;
les choix testés viennent de docs/decisions/0033-cache-semantique-prudent.md.

Ollama n'est jamais appelé : `FauxEmbedder` (sac de mots haché) suffit à
rendre deux questions identiques très proches.

Les tests qui comptent le plus :
- `test_une_action_differente_n_est_jamais_servie` et
  `test_un_nom_different_n_est_jamais_servi` : ce sont les pièges mesurés
  qui passaient avec les embeddings seuls (US-A6-2).
- `test_un_fichier_modifie_invalide_la_reponse` : sinon le cache décrit du
  code qui n'existe plus.
"""
import os
import stat
from datetime import UTC, datetime, timedelta

import pytest

from sensai.knowledge.cache import (
    AnswerCache,
    actions,
    conflict,
    handle_cache_command,
    names,
    standalone,
)
from tests.knowledge.test_rag import FauxEmbedder

QUESTION = "Comment lancer les tests du projet ?"


@pytest.fixture
def projet(tmp_path):
    racine = tmp_path / "projet"
    racine.mkdir()
    (racine / "README.md").write_text("Lancer pytest.\n", encoding="utf-8")
    return racine


@pytest.fixture
def cache(tmp_path, projet):
    return AnswerCache(tmp_path / "donnees" / "cache.db", str(projet), FauxEmbedder(),
                       model="qwen3-coder:30b")


# --- Règles « mots décisifs » (US-A6-2) ---------------------------------------


@pytest.mark.parametrize("a, b", [
    ("Quelle est la taille maximale ?", "Quelle est la taille minimale ?"),
    ("Comment lire un fichier ?", "Comment écrire un fichier ?"),
    ("Comment activer le debug ?", "Comment désactiver le debug ?"),
    ("Comment ajouter un utilisateur ?", "Comment supprimer un utilisateur ?"),
    ("Comment démarrer le serveur ?", "Comment arrêter le serveur ?"),
])
def test_une_action_differente_n_est_jamais_servie(a, b):
    assert conflict(a, b) == "actions différentes"


@pytest.mark.parametrize("a, b", [
    ("Comment installer les dépendances Python ?",
     "Comment installer les dépendances JavaScript ?"),
    ("Que fait purge_sessions ?", "Que fait purge_facts ?"),
    ("Comment corriger KeyError ?", "Comment corriger ModuleNotFoundError ?"),
])
def test_un_nom_different_n_est_jamais_servi(a, b):
    assert conflict(a, b) == "noms différents"


def test_une_reformulation_sans_mot_decisif_passe_les_regles():
    assert conflict("Combien de temps sont gardées les sessions ?",
                    "Quelle est la durée de conservation des sessions ?") is None


def test_limite_connue_un_synonyme_hors_liste_est_refuse():
    # « passer en » n'est pas dans la famille « activer » : le cache refuse,
    # par prudence (ADR-0033, ❌ « environ une reformulation sur cinq »).
    assert conflict("Comment activer le mode debug ?", "Comment passer en mode debug ?")


def test_familles_d_actions_et_noms():
    assert actions("Comment supprimer une branche ?") == {"delete"}
    assert names("Que retourne load_settings en Python 3.12 ?") == {
        "load_settings", "python", "3.12"}
    assert names("Comment lancer les tests ?") == set()


@pytest.mark.parametrize("question, attendu", [
    ("Comment lancer les tests du projet ?", True),
    ("et ensuite ?", False),
    ("corrige ça", False),
    ("Peux-tu réexpliquer ce que tu viens de dire ?", False),
    ("Explique ce code", False),
    ("ok", False),
])
def test_une_question_qui_depend_de_la_conversation_n_est_pas_cachee(question, attendu):
    assert standalone(question) is attendu


# --- Stockage et service (US-A6-1) --------------------------------------------


def test_la_meme_question_est_servie(cache):
    cache.store(QUESTION, "Lancez pytest.", sources=[], seconds=12.0)
    servie = cache.lookup(QUESTION)
    assert servie is not None
    assert servie.answer == "Lancez pytest."
    assert servie.question == QUESTION
    assert servie.similarity >= 0.99


def test_une_question_eloignee_n_est_pas_servie(cache):
    cache.store(QUESTION, "Lancez pytest.", sources=[], seconds=12.0)
    assert cache.lookup("Où est la configuration de la base de données ?") is None


def test_les_regles_s_appliquent_meme_au_dessus_du_seuil(cache):
    cache.store("Comment activer le mode debug ?", "Mettez DEBUG=1.", sources=[], seconds=5)
    assert cache.lookup("Comment désactiver le mode debug ?") is None


def test_un_autre_modele_ou_projet_ne_sert_pas(cache, tmp_path, projet):
    cache.store(QUESTION, "Lancez pytest.", sources=[], seconds=12.0)
    autre_modele = AnswerCache(cache.db_path, str(projet), FauxEmbedder(), model="qwen3:8b")
    autre_projet = AnswerCache(cache.db_path, str(tmp_path), FauxEmbedder(),
                               model="qwen3-coder:30b")
    assert autre_modele.lookup(QUESTION) is None
    assert autre_projet.lookup(QUESTION) is None


def test_une_question_dependante_n_est_ni_servie_ni_enregistree(cache):
    assert cache.store("et ensuite ?", "Ensuite…", sources=[], seconds=3) is False
    assert cache.stats()["entries"] == 0


# --- Fraîcheur (US-A6-2) --------------------------------------------------------


def test_un_fichier_modifie_invalide_la_reponse(cache, projet):
    cache.store(QUESTION, "Lancez pytest.", sources=["README.md"], seconds=12.0)
    assert cache.lookup(QUESTION) is not None
    (projet / "README.md").write_text("Lancer tox.\n", encoding="utf-8")
    assert cache.lookup(QUESTION) is None
    assert cache.stats()["entries"] == 0, "l'entrée périmée doit être retirée"


def test_un_fichier_supprime_invalide_la_reponse(cache, projet):
    cache.store(QUESTION, "Lancez pytest.", sources=["README.md"], seconds=12.0)
    (projet / "README.md").unlink()
    assert cache.lookup(QUESTION) is None


def test_une_entree_trop_ancienne_expire(tmp_path, projet):
    vieux = AnswerCache(tmp_path / "c.db", str(projet), FauxEmbedder(), model="m", ttl_days=30,
                        now=lambda: datetime.now(UTC) - timedelta(days=31))
    vieux.store(QUESTION, "Lancez pytest.", sources=[], seconds=1)
    actuel = AnswerCache(tmp_path / "c.db", str(projet), FauxEmbedder(), model="m", ttl_days=30)
    assert actuel.lookup(QUESTION) is None


# --- Savoir et décider (US-A6-3) ------------------------------------------------


def test_les_statistiques_comptent_les_reponses_servies_et_le_temps_gagne(cache):
    cache.store(QUESTION, "Lancez pytest.", sources=[], seconds=12.0)
    cache.lookup(QUESTION)
    cache.lookup(QUESTION)
    assert cache.stats() == {"entries": 1, "served": 2, "seconds_saved": 24.0}


def test_vider_le_cache(cache):
    cache.store(QUESTION, "Lancez pytest.", sources=[], seconds=12.0)
    assert cache.clear() == 1
    assert cache.lookup(QUESTION) is None


def test_commande_cache(cache):
    cache.store(QUESTION, "Lancez pytest.", sources=[], seconds=12.0)
    cache.lookup(QUESTION)
    sortie = handle_cache_command("/cache", cache)
    assert "1 réponse" in sortie and "servie" in sortie and "12" in sortie
    assert "vidé" in handle_cache_command("/cache clear", cache)
    assert cache.stats()["entries"] == 0
    assert handle_cache_command("/state", cache) is None


def test_commande_cache_sans_cache():
    assert "désactivé" in handle_cache_command("/cache", None)


@pytest.mark.skipif(os.name != "posix", reason="droits Unix")
def test_cache_cree_en_prive(cache):
    assert stat.S_IMODE(cache.db_path.stat().st_mode) == 0o600
