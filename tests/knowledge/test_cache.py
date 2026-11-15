"""
Tests for the semantic cache - feature [A6].

Each block refers to a user story in docs/user-stories/A6-semantic-cache.md;
the tested choices come from docs/decisions/0033-conservative-semantic-cache.md.

Ollama is never called: `FakeEmbedder` (hashed bag of words) is enough to
make two identical questions very close.

The tests that matter most:
- `test_a_different_action_is_never_served` and
  `test_a_different_name_is_never_served`: these are the measured traps
  that got through with embeddings alone (US-A6-2).
- `test_a_modified_file_invalidates_the_answer`: otherwise the cache
  describes code that no longer exists.

The rules are bilingual (French and English roots in `cache.ACTIONS`), so the
parametrized cases keep French questions next to the English ones on purpose.
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
from tests.knowledge.test_rag import FakeEmbedder

QUESTION = "How do I run the project tests?"


@pytest.fixture
def projet(tmp_path):
    racine = tmp_path / "projet"
    racine.mkdir()
    (racine / "README.md").write_text("Run pytest.\n", encoding="utf-8")
    return racine


@pytest.fixture
def cache(tmp_path, projet):
    return AnswerCache(tmp_path / "donnees" / "cache.db", str(projet), FakeEmbedder(),
                       model="qwen3-coder:30b")


# --- "Decisive words" rules (US-A6-2) ----------------------------------------------


@pytest.mark.parametrize("a, b", [
    ("Quelle est la taille maximale ?", "Quelle est la taille minimale ?"),
    ("Comment lire un fichier ?", "Comment écrire un fichier ?"),
    ("Comment activer le debug ?", "Comment désactiver le debug ?"),
    ("Comment ajouter un utilisateur ?", "Comment supprimer un utilisateur ?"),
    ("Comment démarrer le serveur ?", "Comment arrêter le serveur ?"),
    ("What is the maximum size?", "What is the minimum size?"),
    ("How do I read a file?", "How do I write a file?"),
    ("How do I enable debug?", "How do I disable debug?"),
    ("How do I add a user?", "How do I delete a user?"),
    ("How do I start the server?", "How do I stop the server?"),
])
def test_a_different_action_is_never_served(a, b):
    assert conflict(a, b) == "different actions"


@pytest.mark.parametrize("a, b", [
    ("Comment installer les dépendances Python ?",
     "Comment installer les dépendances JavaScript ?"),
    ("Que fait purge_sessions ?", "Que fait purge_facts ?"),
    ("Comment corriger KeyError ?", "Comment corriger ModuleNotFoundError ?"),
    ("How do I install the Python dependencies?",
     "How do I install the JavaScript dependencies?"),
    ("What does purge_sessions do?", "What does purge_facts do?"),
])
def test_a_different_name_is_never_served(a, b):
    assert conflict(a, b) == "different names"


def test_a_rephrasing_without_decisive_word_passes_the_rules():
    assert conflict("Combien de temps sont gardées les sessions ?",
                    "Quelle est la durée de conservation des sessions ?") is None
    assert conflict("How long are sessions kept?",
                    "What is the retention period for sessions?") is None


def test_known_limit_a_synonym_outside_the_list_is_refused():
    # "passer en" / "turn on" are not in the "enable" family: the cache refuses,
    # to be safe (ADR-0033, ❌ "about one rephrasing in five").
    assert conflict("Comment activer le mode debug ?", "Comment passer en mode debug ?")
    assert conflict("How do I enable debug mode?", "How do I turn on debug mode?")


def test_action_families_and_names():
    assert actions("Comment supprimer une branche ?") == {"delete"}
    assert actions("How do I delete a branch?") == {"delete"}
    assert names("What does load_settings return in Python 3.12?") == {
        "load_settings", "python", "3.12"}
    assert names("How to run the tests?") == set()


@pytest.mark.parametrize("question, expected", [
    ("Comment lancer les tests du projet ?", True),
    ("et ensuite ?", False),
    ("corrige ça", False),
    ("Peux-tu réexpliquer ce que tu viens de dire ?", False),
    ("Explique ce code", False),
    ("ok", False),
    ("How do I run the project tests?", True),
    ("and then?", False),
    ("fix that", False),
    ("Can you explain again what you just said?", False),
    ("Explain this code", False),
])
def test_a_conversation_dependent_question_is_not_cached(question, expected):
    assert standalone(question) is expected


# --- Storage and serving (US-A6-1) ---------------------------------------------


def test_the_same_question_is_served(cache):
    cache.store(QUESTION, "Run pytest.", sources=[], seconds=12.0)
    servie = cache.lookup(QUESTION)
    assert servie is not None
    assert servie.answer == "Run pytest."
    assert servie.question == QUESTION
    assert servie.similarity >= 0.99


def test_a_distant_question_is_not_served(cache):
    cache.store(QUESTION, "Run pytest.", sources=[], seconds=12.0)
    assert cache.lookup("Where is the database configuration?") is None


def test_rules_apply_even_above_the_threshold(cache):
    cache.store("How do I enable debug mode?", "Set DEBUG=1.", sources=[], seconds=5)
    assert cache.lookup("How do I disable debug mode?") is None


def test_another_model_or_project_does_not_serve(cache, tmp_path, projet):
    cache.store(QUESTION, "Run pytest.", sources=[], seconds=12.0)
    autre_modele = AnswerCache(cache.db_path, str(projet), FakeEmbedder(), model="qwen3:8b")
    autre_projet = AnswerCache(cache.db_path, str(tmp_path), FakeEmbedder(),
                               model="qwen3-coder:30b")
    assert autre_modele.lookup(QUESTION) is None
    assert autre_projet.lookup(QUESTION) is None


def test_a_dependent_question_is_neither_served_nor_stored(cache):
    assert cache.store("and then?", "Then…", sources=[], seconds=3) is False
    assert cache.stats()["entries"] == 0


# --- Freshness (US-A6-2) ---------------------------------------------------------


def test_a_modified_file_invalidates_the_answer(cache, projet):
    cache.store(QUESTION, "Run pytest.", sources=["README.md"], seconds=12.0)
    assert cache.lookup(QUESTION) is not None
    (projet / "README.md").write_text("Run tox.\n", encoding="utf-8")
    assert cache.lookup(QUESTION) is None
    assert cache.stats()["entries"] == 0, "the stale entry must be removed"


def test_a_deleted_file_invalidates_the_answer(cache, projet):
    cache.store(QUESTION, "Run pytest.", sources=["README.md"], seconds=12.0)
    (projet / "README.md").unlink()
    assert cache.lookup(QUESTION) is None


def test_a_too_old_entry_expires(tmp_path, projet):
    vieux = AnswerCache(tmp_path / "c.db", str(projet), FakeEmbedder(), model="m", ttl_days=30,
                        now=lambda: datetime.now(UTC) - timedelta(days=31))
    vieux.store(QUESTION, "Run pytest.", sources=[], seconds=1)
    actuel = AnswerCache(tmp_path / "c.db", str(projet), FakeEmbedder(), model="m", ttl_days=30)
    assert actuel.lookup(QUESTION) is None


# --- Know and decide (US-A6-3) --------------------------------------------------


def test_stats_count_served_answers_and_time_saved(cache):
    cache.store(QUESTION, "Run pytest.", sources=[], seconds=12.0)
    cache.lookup(QUESTION)
    cache.lookup(QUESTION)
    assert cache.stats() == {"entries": 1, "served": 2, "seconds_saved": 24.0}


def test_clear_the_cache(cache):
    cache.store(QUESTION, "Run pytest.", sources=[], seconds=12.0)
    assert cache.clear() == 1
    assert cache.lookup(QUESTION) is None


def test_cache_command(cache):
    cache.store(QUESTION, "Run pytest.", sources=[], seconds=12.0)
    cache.lookup(QUESTION)
    sortie = handle_cache_command("/cache", cache)
    assert "1 answer" in sortie and "served" in sortie and "12" in sortie
    assert "cleared" in handle_cache_command("/cache clear", cache)
    assert cache.stats()["entries"] == 0
    assert handle_cache_command("/state", cache) is None


def test_cache_command_without_cache():
    assert "disabled" in handle_cache_command("/cache", None)


@pytest.mark.skipif(os.name != "posix", reason="Unix permissions")
def test_cache_created_private(cache):
    assert stat.S_IMODE(cache.db_path.stat().st_mode) == 0o600
