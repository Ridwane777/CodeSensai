"""Teste les personas de l'agent — feature [A5], ADR-0042."""
import pytest

from sensai.knowledge.persona import (
    DEFAULT_PERSONA_ID,
    Persona,
    PersonaError,
    PersonaStore,
    handle_persona_command,
)


def test_store_sans_config_a_une_persona_par_defaut():
    store = PersonaStore.from_config(None)
    assert store.names() == [DEFAULT_PERSONA_ID]
    assert store.default().id == DEFAULT_PERSONA_ID


def test_store_charge_les_profils_de_la_config():
    store = PersonaStore.from_config({
        "default": "juridique",
        "profiles": [
            {"id": "assistant", "name": "Sensai", "role": "assistant", "tone": "neutre",
             "scope": "le projet"},
            {"id": "juridique", "name": "Maître Sensai", "role": "assistant juridique",
             "tone": "formel", "scope": "droit uniquement, pas de code"},
        ],
    })
    assert store.names() == ["assistant", "juridique"]
    assert store.default().id == "juridique"
    assert store.get("juridique").name == "Maître Sensai"


def test_profil_incomplet_refuse():
    profil = {"id": "x", "name": "X", "tone": "x", "scope": "x"}
    with pytest.raises(PersonaError, match="role"):
        PersonaStore.from_config({"profiles": [profil]})


def test_id_en_double_refuse():
    profil = {"id": "x", "name": "X", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="double"):
        PersonaStore.from_config({"profiles": [profil, dict(profil)]})


def test_persona_par_defaut_inconnue_refusee():
    with pytest.raises(PersonaError, match="inconnue"):
        PersonaStore.from_config({
            "default": "fantome",
            "profiles": [{"id": "x", "name": "X", "role": "r", "tone": "t", "scope": "s"}],
        })


def test_get_persona_inconnue_leve():
    store = PersonaStore.from_config(None)
    with pytest.raises(PersonaError, match="inconnue"):
        store.get("fantome")


def test_as_prompt_contient_nom_role_ton_et_perimetre():
    texte = Persona(id="t", name="Tuteur", role="tuteur de maths", tone="pédagogue",
                     scope="mathématiques uniquement").as_prompt()
    assert "Tuteur" in texte
    assert "tuteur de maths" in texte
    assert "pédagogue" in texte
    assert "mathématiques uniquement" in texte


@pytest.fixture
def store():
    return PersonaStore.from_config({
        "default": "assistant",
        "profiles": [
            {"id": "assistant", "name": "Sensai", "role": "assistant", "tone": "neutre",
             "scope": "le projet"},
            {"id": "juridique", "name": "Maître Sensai", "role": "assistant juridique",
             "tone": "formel", "scope": "droit uniquement"},
        ],
    })


def test_commande_non_reconnue_retourne_none(store):
    assert handle_persona_command("bonjour", store, "assistant") is None


def test_persona_sans_argument_affiche_lactive(store):
    texte, actif = handle_persona_command("/persona", store, "assistant")
    assert "assistant" in texte
    assert actif == "assistant"


def test_persona_list_marque_lactive(store):
    texte, actif = handle_persona_command("/persona list", store, "juridique")
    assert "* juridique" in texte
    assert "  assistant" in texte
    assert actif == "juridique"


def test_persona_use_change_la_persona_active(store):
    texte, actif = handle_persona_command("/persona use juridique", store, "assistant")
    assert actif == "juridique"
    assert "juridique" in texte
    assert "historique" in texte.lower()


def test_persona_use_inconnue_ne_change_rien(store):
    texte, actif = handle_persona_command("/persona use fantome", store, "assistant")
    assert actif == "assistant"
    assert "[Erreur]" in texte


def test_persona_use_sans_id_affiche_usage(store):
    texte, actif = handle_persona_command("/persona use", store, "assistant")
    assert "Usage" in texte
    assert actif == "assistant"


# --- Validation robuste d'une config mal écrite (revue PR #94) ------------
# Une entrée qui ne respecte pas la forme attendue doit lever PersonaError,
# jamais une AttributeError/TypeError Python qui plante le CLI avec une trace.


def test_personas_pas_un_objet_refuse():
    with pytest.raises(PersonaError, match="objet"):
        PersonaStore.from_config("abc")


def test_profil_pas_un_objet_refuse():
    with pytest.raises(PersonaError, match="objet"):
        PersonaStore.from_config({"profiles": ["x"]})


def test_champ_qui_n_est_pas_une_chaine_refuse():
    profil = {"id": ["a"], "name": "X", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="id"):
        PersonaStore.from_config({"profiles": [profil]})


def test_champ_entier_refuse():
    profil = {"id": "x", "name": 1, "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="name"):
        PersonaStore.from_config({"profiles": [profil]})


def test_champ_vide_refuse():
    profil = {"id": "x", "name": "", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="name"):
        PersonaStore.from_config({"profiles": [profil]})


def test_champ_uniquement_des_espaces_refuse():
    profil = {"id": "x", "name": "   ", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="name"):
        PersonaStore.from_config({"profiles": [profil]})


def test_default_pas_une_chaine_refuse():
    profil = {"id": "x", "name": "X", "role": "r", "tone": "t", "scope": "s"}
    with pytest.raises(PersonaError, match="default"):
        PersonaStore.from_config({"profiles": [profil], "default": 1})


def test_personas_vide_refuse_comme_profiles_vide():
    """« {} » et « {"profiles": []} » disent tous les deux « aucun profil » :
    même traitement (erreur), pour ne pas laisser {} passer par accident."""
    with pytest.raises(PersonaError, match="profiles"):
        PersonaStore.from_config({})


def test_tools_disabled_invalides_refuses():
    with pytest.raises(PersonaError, match=r"tools\.disabled"):
        PersonaStore.from_config({
            "profiles": [{"id": "x", "name": "X", "role": "r", "tone": "t", "scope": "s",
                          "tools": {"disabled": "pas une liste"}}],
        })


def test_le_routage_par_mots_cles_est_refuse_explicitement():
    """ADR-0056, point 4 : une clé `keywords` qui ne fait plus rien arrête le programme."""
    with pytest.raises(PersonaError, match="mots-clés a été retiré"):
        PersonaStore.from_config({"profiles": [
            {"id": "juridique", "name": "Maître", "role": "r", "tone": "t", "scope": "s",
             "keywords": ["contrat"]}]})


def test_persona_add_n_existe_plus(store):
    """ADR-0056, point 4 : plus de persona créée en cours de session."""
    texte, actif = handle_persona_command('/persona add medecin "Dr" "r" "t" "s"', store,
                                          "assistant")
    assert texte.startswith("Usage : /persona | /persona list | /persona use <id>")
    assert actif == "assistant"

