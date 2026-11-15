"""Tests the agent personas - feature [A5], ADR-0042."""
import pytest

from sensai.knowledge.persona import (
    DEFAULT_PERSONA_ID,
    Persona,
    PersonaError,
    PersonaStore,
    handle_persona_command,
)


def test_store_without_config_has_a_default_persona():
    store = PersonaStore.from_config(None)
    assert store.names() == [DEFAULT_PERSONA_ID]
    assert store.default().id == DEFAULT_PERSONA_ID


def test_store_loads_config_profiles():
    store = PersonaStore.from_config({
        "default": "juridique",
        "profiles": [
            {"id": "assistant", "name": "CodeSensai", "role": "assistant", "tone": "neutral",
             "scope": "the project"},
            {"id": "juridique", "name": "Counsel CodeSensai", "role": "legal assistant",
             "tone": "formal", "scope": "law only, no code"},
        ],
    })
    assert store.names() == ["assistant", "juridique"]
    assert store.default().id == "juridique"
    assert store.get("juridique").name == "Counsel CodeSensai"


def test_incomplete_profile_refused():
    profil = {"id": "x", "name": "X", "tone": "x", "scope": "x"}
    with pytest.raises(PersonaError, match="role"):
        PersonaStore.from_config({"profiles": [profil]})


def test_duplicate_id_refused():
    profil = {"id": "x", "name": "X", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="duplicate"):
        PersonaStore.from_config({"profiles": [profil, dict(profil)]})


def test_unknown_default_persona_refused():
    with pytest.raises(PersonaError, match="unknown"):
        PersonaStore.from_config({
            "default": "ghost",
            "profiles": [{"id": "x", "name": "X", "role": "r", "tone": "t", "scope": "s"}],
        })


def test_get_unknown_persona_raises():
    store = PersonaStore.from_config(None)
    with pytest.raises(PersonaError, match="unknown"):
        store.get("ghost")


def test_as_prompt_has_name_role_tone_and_scope():
    texte = Persona(id="t", name="Tutor", role="math tutor", tone="patient",
                     scope="mathematics only").as_prompt()
    assert "Tutor" in texte
    assert "math tutor" in texte
    assert "patient" in texte
    assert "mathematics only" in texte


@pytest.fixture
def store():
    return PersonaStore.from_config({
        "default": "assistant",
        "profiles": [
            {"id": "assistant", "name": "CodeSensai", "role": "assistant", "tone": "neutral",
             "scope": "the project"},
            {"id": "juridique", "name": "Counsel CodeSensai", "role": "legal assistant",
             "tone": "formal", "scope": "law only"},
        ],
    })


def test_unrecognized_command_returns_none(store):
    assert handle_persona_command("hello", store, "assistant") is None


def test_persona_without_argument_shows_active(store):
    texte, actif = handle_persona_command("/persona", store, "assistant")
    assert "assistant" in texte
    assert actif == "assistant"


def test_persona_list_marks_active(store):
    texte, actif = handle_persona_command("/persona list", store, "juridique")
    assert "* juridique" in texte
    assert "  assistant" in texte
    assert actif == "juridique"


def test_persona_use_changes_active_persona(store):
    texte, actif = handle_persona_command("/persona use juridique", store, "assistant")
    assert actif == "juridique"
    assert "juridique" in texte
    assert "history" in texte.lower()


def test_persona_use_unknown_changes_nothing(store):
    texte, actif = handle_persona_command("/persona use fantome", store, "assistant")
    assert actif == "assistant"
    assert "[Error]" in texte


def test_persona_use_without_id_shows_usage(store):
    texte, actif = handle_persona_command("/persona use", store, "assistant")
    assert "Usage" in texte
    assert actif == "assistant"


# --- Robust validation of a badly written config (PR #94 review) ---------
# An entry that does not match the expected shape must raise PersonaError,
# never a Python AttributeError/TypeError that crashes the CLI with a traceback.


def test_personas_not_an_object_refused():
    with pytest.raises(PersonaError, match="object"):
        PersonaStore.from_config("abc")


def test_profile_not_an_object_refused():
    with pytest.raises(PersonaError, match="object"):
        PersonaStore.from_config({"profiles": ["x"]})


def test_non_string_field_refused():
    profil = {"id": ["a"], "name": "X", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="id"):
        PersonaStore.from_config({"profiles": [profil]})


def test_integer_field_refused():
    profil = {"id": "x", "name": 1, "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="name"):
        PersonaStore.from_config({"profiles": [profil]})


def test_empty_field_refused():
    profil = {"id": "x", "name": "", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="name"):
        PersonaStore.from_config({"profiles": [profil]})


def test_whitespace_only_field_refused():
    profil = {"id": "x", "name": "   ", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="name"):
        PersonaStore.from_config({"profiles": [profil]})


def test_default_not_a_string_refused():
    profil = {"id": "x", "name": "X", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="default"):
        PersonaStore.from_config({"profiles": [profil], "default": 1})


def test_empty_personas_refused_like_empty_profiles():
    """`{}` and `{"profiles": []}` both mean "no profile": same handling
    (error), so that {} does not slip through by accident."""
    with pytest.raises(PersonaError, match="profiles"):
        PersonaStore.from_config({})


def test_invalid_tools_disabled_refused():
    with pytest.raises(PersonaError, match=r"tools\.disabled"):
        PersonaStore.from_config({
            "profiles": [{"id": "x", "name": "X", "role": "r", "tone": "t", "scope": "s",
                          "tools": {"disabled": "not a list"}}],
        })


def test_keyword_routing_is_explicitly_refused():
    """ADR-0056, point 4: a `keywords` key that no longer does anything stops the program."""
    with pytest.raises(PersonaError, match="keyword routing was removed"):
        PersonaStore.from_config({"profiles": [
            {"id": "juridique", "name": "Counsel", "role": "r", "tone": "t", "scope": "s",
             "keywords": ["contract"]}]})


def test_persona_add_no_longer_exists(store):
    """ADR-0056, point 4: no more persona created mid-session."""
    texte, actif = handle_persona_command('/persona add doctor "Dr" "r" "t" "s"', store,
                                          "assistant")
    assert texte.startswith("Usage: /persona | /persona list | /persona use <id>")
    assert actif == "assistant"

