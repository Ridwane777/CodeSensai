"""
Teste la mémoire structurée de faits — feature [M3], ADR-0030.

`test_un_fait_survit_a_une_nouvelle_instance` porte la promesse de M3 (« sur
la durée ») ; `test_la_memoire_est_propre_au_projet` protège US-M3-3.
"""
import pytest

from sensai.knowledge.facts import MAX_PROMPT_ENTITIES, FactError, FactStore


@pytest.fixture
def base(tmp_path):
    return tmp_path / "donnees" / "memory.db"


@pytest.fixture
def faits(base):
    return FactStore(base, project="/projets/demo")


# --- US-M3-1 : retenir, sans doublon, sur la durée -------------------------------


def test_retenir_puis_retrouver(faits):
    resultat = faits.remember("auth", "version_redis", "7")

    assert resultat["change"] == "created"
    assert faits.recall(entity="auth") == [
        {"entity": "auth", "attribute": "version_redis", "value": "7",
         "updated_at": faits.recall(entity="auth")[0]["updated_at"]}
    ]


def test_un_fait_survit_a_une_nouvelle_instance(base):
    FactStore(base, project="/p").remember("auth", "version_redis", "7")

    assert FactStore(base, project="/p").recall(entity="auth")[0]["value"] == "7"


def test_pas_de_doublon_noms_compares_sans_casse_ni_espaces(faits):
    faits.remember("auth", "version_redis", "7")

    resultat = faits.remember(" Auth ", "Version_Redis", "7")

    assert resultat["change"] == "unchanged"
    assert len(faits.recall(entity="AUTH")) == 1


def test_replace_remplace_la_valeur(faits):
    faits.remember("auth", "version_redis", "7")

    resultat = faits.remember("auth", "version_redis", "8")

    assert resultat["change"] == "updated"
    assert resultat["old_values"] == ["7"]
    assert [f["value"] for f in faits.recall(entity="auth")] == ["8"]


def test_add_ajoute_une_valeur_de_plus(faits):
    faits.remember("auth", "depend_de", "redis", mode="add")
    faits.remember("auth", "depend_de", "postgres", mode="add")

    valeurs = sorted(f["value"] for f in faits.recall(entity="auth", attribute="depend_de"))
    assert valeurs == ["postgres", "redis"]


@pytest.mark.parametrize(
    ("entite", "attribut", "valeur", "mode"),
    [("", "a", "v", "replace"), ("e", "  ", "v", "replace"), ("e", "a", "", "replace"),
     ("e", "a", "v", "delete"), ("e" * 101, "a", "v", "replace"), ("e", "a", "v" * 501, "add")],
)
def test_faits_invalides_refuses(faits, entite, attribut, valeur, mode):
    with pytest.raises(FactError):
        faits.remember(entite, attribut, valeur, mode=mode)

    assert faits.entities() == []


# --- US-M3-2 : retrouver, dans les deux sens ------------------------------------


def test_relations_inverses(faits):
    faits.remember("auth", "depend_de", "redis", mode="add")
    faits.remember("cache", "depend_de", "Redis", mode="add")
    faits.remember("billing", "depend_de", "postgres", mode="add")

    entites = sorted(f["entity"] for f in faits.recall(value="redis"))
    assert entites == ["auth", "cache"]


def test_recherche_sans_resultat(faits):
    assert faits.recall(entity="inconnu") == []


def test_recherche_sans_critere_refusee(faits):
    with pytest.raises(FactError):
        faits.recall()


# --- US-M3-3 : corriger, oublier, historique, par projet --------------------------


def test_l_ancienne_valeur_reste_dans_l_historique(faits):
    faits.remember("auth", "version_redis", "7")
    faits.remember("auth", "version_redis", "8")

    historique = faits.history("auth")

    assert historique[0]["action"] == "replace"
    assert historique[0]["old_value"] == "7"
    assert historique[0]["new_value"] == "8"


def test_oublier_un_fait_precis(faits):
    faits.remember("auth", "depend_de", "redis", mode="add")
    faits.remember("auth", "depend_de", "postgres", mode="add")

    assert faits.forget("auth", "depend_de", "redis") == 1

    assert [f["value"] for f in faits.recall(entity="auth")] == ["postgres"]
    assert faits.history("auth")[0]["action"] == "forget"


def test_oublier_toute_une_entite(faits):
    faits.remember("auth", "version_redis", "7")
    faits.remember("auth", "responsable", "Méric")

    assert faits.forget("auth") == 2
    assert faits.recall(entity="auth") == []


def test_la_memoire_est_propre_au_projet(base):
    FactStore(base, project="/projet-a").remember("auth", "version_redis", "7")

    assert FactStore(base, project="/projet-b").recall(entity="auth") == []


def test_fichier_lisible_par_le_seul_proprietaire(faits, base):
    faits.remember("auth", "version_redis", "7")

    assert base.stat().st_mode & 0o777 == 0o600
    assert base.parent.stat().st_mode & 0o777 == 0o700


# --- Prompt système (ADR-0030, décision 3) ---------------------------------------


def test_sans_fait_pas_de_prompt(faits):
    assert faits.as_prompt() == ""


def test_le_prompt_liste_les_entites_pas_les_faits(faits):
    faits.remember("auth", "version_redis", "7")
    faits.remember("sandbox", "responsable", "Méric")

    prompt = faits.as_prompt()

    assert "auth" in prompt and "sandbox" in prompt
    assert "Méric" not in prompt
    assert "recall_facts" in prompt
    assert "donnée" in prompt.lower()


def test_le_prompt_est_limite(faits):
    for i in range(MAX_PROMPT_ENTITIES + 5):
        faits.remember(f"service{i}", "port", str(8000 + i))

    prompt = faits.as_prompt()

    assert prompt.count("service") <= MAX_PROMPT_ENTITIES + 1
    assert "autres" in prompt


def test_apercu_montre_l_ancienne_et_la_nouvelle_valeur(faits):
    faits.remember("auth", "version_redis", "7")

    apercu = faits.preview("auth", "version_redis", "8")

    assert "7" in apercu and "8" in apercu
    assert [f["value"] for f in faits.recall(entity="auth")] == ["7"]


def test_l_historique_distingue_creation_ajout_et_remplacement(faits):
    """Essai réel du 2026-10-17 : un fait créé apparaissait comme « replace »."""
    faits.remember("auth", "version_redis", "7")
    faits.remember("auth", "depend_de", "redis", mode="add")
    faits.remember("auth", "depend_de", "postgres", mode="add")
    faits.remember("auth", "version_redis", "8")

    actions = [(h["attribute"], h["action"]) for h in reversed(faits.history("auth"))]

    assert actions == [("version_redis", "create"), ("depend_de", "create"),
                       ("depend_de", "add"), ("version_redis", "replace")]


# --- Cohérence des noms (essai réel du 2026-10-17 : « version redis » et
# « redis_version » enregistrés à côté de l'ancien fait au lieu de le remplacer)


def test_espaces_tirets_et_soulignes_designent_le_meme_attribut(faits):
    faits.remember("auth", "version redis", "7")

    resultat = faits.remember("Auth", "Version-Redis", "8")

    assert resultat["change"] == "updated"
    assert [f["value"] for f in faits.recall(entity="auth")] == ["8"]
    assert faits.recall(entity="auth", attribute="version_redis")[0]["value"] == "8"


def test_le_resultat_liste_les_autres_attributs_de_l_entite(faits):
    faits.remember("auth", "utilise_redis", "7")
    faits.remember("auth", "port", "8080")

    resultat = faits.remember("auth", "redis_version", "8")

    assert ("utilise_redis", ["7"]) in resultat["others"]
    assert ("port", ["8080"]) in resultat["others"]


def test_l_apercu_montre_les_attributs_existants_pour_reperer_un_doublon(faits):
    faits.remember("auth", "utilise_redis", "7")

    apercu = faits.preview("auth", "redis_version", "8")

    assert "utilise_redis" in apercu and "7" in apercu


def test_l_apercu_d_une_nouvelle_entite_montre_les_entites_connues(faits):
    faits.remember("service auth", "port", "8080")

    apercu = faits.preview("auth", "port", "9090")

    assert "service auth" in apercu


def test_le_prompt_demande_de_consulter_avant_d_enregistrer(faits):
    faits.remember("auth", "port", "8080")

    assert "avant" in faits.as_prompt().lower() and "recall_facts" in faits.as_prompt()
