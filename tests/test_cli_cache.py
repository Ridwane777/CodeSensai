"""
Le cache des réponses dans le CLI — feature [A6] (ADR-0033).

Réutilise le CLI piloté de tests/test_cli_rag.py : le modèle de chat est un
faux qui répond « D'accord. » et compte les appels.
"""
from sensai.knowledge.persona import PersonaStore
from tests.test_cli_rag import lancer, projet  # noqa: F401  (fixtures)

QUESTION = "Où vérifie-t-on le token de connexion ?"


def test_une_question_reposee_ne_rappelle_pas_le_modele(lancer, capsys):  # noqa: F811
    envoyes, _ = lancer([QUESTION, QUESTION], cache=True)
    assert len(envoyes) == 1, "la seconde réponse doit venir du cache"
    assert "depuis le cache" in capsys.readouterr().out


def test_again_redemande_au_modele(lancer):  # noqa: F811
    envoyes, _ = lancer([QUESTION, QUESTION, "/again"], cache=True)
    assert len(envoyes) == 2


def test_no_cache_rappelle_toujours_le_modele(lancer):  # noqa: F811
    envoyes, _ = lancer([QUESTION, QUESTION], cache=False)
    assert len(envoyes) == 2


def test_une_question_qui_depend_de_la_conversation_rappelle_le_modele(lancer):  # noqa: F811
    envoyes, _ = lancer(["et ensuite ?", "et ensuite ?"], cache=True)
    assert len(envoyes) == 2


def test_commande_cache(lancer, capsys):  # noqa: F811
    lancer([QUESTION, QUESTION, "/cache"], cache=True)
    assert "servie(s) 1 fois" in capsys.readouterr().out


def test_persona_qui_restreint_les_outils_ignore_le_cache(lancer):  # noqa: F811
    """Revue PR #95 : une réponse ne doit pas franchir la restriction d'une
    persona en étant resservie telle quelle depuis le cache (A6)."""
    personas = PersonaStore.from_config({
        "default": "tuteur",
        "profiles": [
            {"id": "tuteur", "name": "Prof Sensai", "role": "tuteur", "tone": "doux",
             "scope": "pedagogie", "tools": {"disabled": ["run_code"]}},
        ],
    })
    envoyes, _ = lancer([QUESTION, QUESTION], cache=True, personas=personas)
    assert len(envoyes) == 2, "le cache ne doit jamais être consulté pour cette persona"


def test_persona_sans_restriction_garde_le_cache(lancer):  # noqa: F811
    personas = PersonaStore.from_config({
        "default": "assistant",
        "profiles": [
            {"id": "assistant", "name": "Sensai", "role": "assistant", "tone": "neutre",
             "scope": "le projet"},
        ],
    })
    envoyes, _ = lancer([QUESTION, QUESTION], cache=True, personas=personas)
    assert len(envoyes) == 1, "une persona sans restriction d'outils garde le cache normal"




