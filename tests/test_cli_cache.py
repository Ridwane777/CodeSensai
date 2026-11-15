"""
The answer cache in the CLI - feature [A6] (ADR-0033).

Reuses the driven CLI from tests/test_cli_rag.py: the chat model is a fake
that answers "Got it." and counts the calls.
"""
from sensai.knowledge.persona import PersonaStore
from tests.test_cli_rag import lancer, projet  # noqa: F401  (fixtures)

QUESTION = "Where is the login token checked?"


def test_a_repeated_question_does_not_call_the_model_again(lancer, capsys):  # noqa: F811
    envoyes, _ = lancer([QUESTION, QUESTION], cache=True)
    assert len(envoyes) == 1, "the second answer must come from the cache"
    # Production string in src/sensai/ui.py is still French.
    assert "from cache" in capsys.readouterr().out


def test_again_asks_the_model_again(lancer):  # noqa: F811
    envoyes, _ = lancer([QUESTION, QUESTION, "/again"], cache=True)
    assert len(envoyes) == 2


def test_no_cache_always_calls_the_model(lancer):  # noqa: F811
    envoyes, _ = lancer([QUESTION, QUESTION], cache=False)
    assert len(envoyes) == 2


def test_a_context_dependent_question_calls_the_model(lancer):  # noqa: F811
    envoyes, _ = lancer(["and what about that?", "and what about that?"], cache=True)
    assert len(envoyes) == 2


def test_cache_command(lancer, capsys):  # noqa: F811
    lancer([QUESTION, QUESTION, "/cache"], cache=True)
    assert "served 1 time(s)" in capsys.readouterr().out


def test_persona_restricting_tools_skips_the_cache(lancer):  # noqa: F811
    """PR #95 review: an answer must not bypass a persona's restriction by
    being served again as is from the cache (A6)."""
    personas = PersonaStore.from_config({
        "default": "tuteur",
        "profiles": [
            {"id": "tuteur", "name": "Prof CodeSensai", "role": "tutor", "tone": "gentle",
             "scope": "teaching", "tools": {"disabled": ["run_code"]}},
        ],
    })
    envoyes, _ = lancer([QUESTION, QUESTION], cache=True, personas=personas)
    assert len(envoyes) == 2, "the cache must never be consulted for this persona"


def test_persona_without_restriction_keeps_the_cache(lancer):  # noqa: F811
    personas = PersonaStore.from_config({
        "default": "assistant",
        "profiles": [
            {"id": "assistant", "name": "CodeSensai", "role": "assistant", "tone": "neutral",
             "scope": "the project"},
        ],
    })
    envoyes, _ = lancer([QUESTION, QUESTION], cache=True, personas=personas)
    assert len(envoyes) == 1, "a persona without tool restrictions keeps the normal cache"
