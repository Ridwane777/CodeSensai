"""
Teste le registre des versions de prompts — feature [A4], ADR-0010.

Le principe testé : une version est immuable, le marque-page `active` est
mobile. `test_retour_en_arriere_ne_perd_rien` est la Definition of Done :
revenir à une ancienne version en une commande, sans rien effacer.
"""
import json

import pytest

from sensai.knowledge.prompt_versions import INDEX_FILE, PromptStore


@pytest.fixture
def store(tmp_path):
    """Un registre avec un prompt `system` en deux versions, la v2 active."""
    s = PromptStore(tmp_path)
    s.save("system", "Tu es CodeSensei.", "prompt initial", author="Alice", date="2026-09-28")
    s.save("system", "Tu es CodeSensei.\nRéponds en français.", "langue", author="Bob",
           date="2026-10-12")
    s.use("system", "v2")
    return s


def test_registre_absent(tmp_path):
    s = PromptStore(tmp_path)

    assert not s.exists()
    assert s.names() == []


def test_premiere_version_d_un_prompt_devient_active(tmp_path):
    """Sans version active, l'agent n'aurait rien à lire."""
    s = PromptStore(tmp_path)

    assert s.save("memory", "Consigne", "initial", author="Alice") == "v1"
    assert s.active("memory") == "v1"
    assert s.load("memory") == "Consigne"
    assert (tmp_path / "memory" / "v1.txt").read_text(encoding="utf-8") == "Consigne"


def test_save_ne_deplace_pas_le_marque_page(store):
    """On range d'abord, on met en service ensuite (ADR-0010)."""
    nouvelle = store.save("system", "Tu es CodeSensei, concis.", "concision", author="Alice")

    assert nouvelle == "v3"
    assert store.active("system") == "v2"


def test_save_refuse_un_texte_deja_range(store):
    """US-A4-2 : un texte inchangé ne crée pas de version."""
    with pytest.raises(ValueError, match="v1"):
        store.save("system", "Tu es CodeSensei.\n", "doublon", author="Alice")


def test_historique_du_plus_recent_au_plus_ancien(store):
    """US-A4-1 : date, auteur, description, et quelle version est active."""
    versions = store.history("system")

    assert [v["id"] for v in versions] == ["v2", "v1"]
    assert versions[0] == {
        "id": "v2",
        "date": "2026-10-12",
        "author": "Bob",
        "description": "langue",
        "active": True,
    }
    assert versions[1]["active"] is False


def test_retour_en_arriere_ne_perd_rien(store):
    """US-A4-3 / DoD : déplacer le marque-page, puis revenir à la plus récente."""
    store.use("system", "v1")

    assert store.load("system") == "Tu es CodeSensei."
    assert [v["id"] for v in store.history("system")] == ["v2", "v1"]

    store.use("system", "v2")
    assert store.load("system").endswith("Réponds en français.")


def test_marque_page_conserve_sur_disque(store, tmp_path):
    """Le prochain lancement de `sensai` doit voir le choix."""
    store.use("system", "v1")

    assert PromptStore(tmp_path).active("system") == "v1"


def test_version_designee_par_numero_seul(store):
    assert store.resolve("system", "1") == "v1"
    assert store.resolve("system", "v2") == "v2"


def test_version_ou_prompt_inconnus(store):
    with pytest.raises(KeyError):
        store.use("system", "v9")
    with pytest.raises(KeyError):
        store.load("inexistant")


def test_charger_une_version_precise(store):
    assert store.load("system", "v1") == "Tu es CodeSensei."


def test_diff_entre_deux_versions(store):
    """US-A4-1 : différences ligne par ligne, v2 = l'active par défaut."""
    diff = store.diff("system", "v1")

    assert "+Réponds en français." in diff
    assert "system v1" in diff and "system v2" in diff


def test_diff_de_versions_identiques_vide(store):
    assert store.diff("system", "v2", "v2") == ""


def test_index_lisible_et_versions_rangees_par_prompt(store, tmp_path):
    index = json.loads((tmp_path / INDEX_FILE).read_text(encoding="utf-8"))

    assert index["system"]["active"] == "v2"
    assert [v["id"] for v in index["system"]["versions"]] == ["v1", "v2"]
    assert (tmp_path / "system" / "v2.txt").is_file()


def test_registre_coherent(store):
    assert store.check() == []


def test_version_modifiee_detectee(store, tmp_path):
    """Une version rangée ne doit jamais changer : la CI le signale."""
    (tmp_path / "system" / "v1.txt").write_text("modifié en douce", encoding="utf-8")

    problemes = store.check()

    assert any("system v1" in p for p in problemes)


def test_fichier_de_version_manquant_detecte(store, tmp_path):
    (tmp_path / "system" / "v2.txt").unlink()

    assert any("system v2" in p for p in store.check())


def test_numeros_en_double_detectes(store, tmp_path):
    """Cas de deux branches qui créent chacune une v2, fusionnées à la main."""
    chemin = tmp_path / INDEX_FILE
    index = json.loads(chemin.read_text(encoding="utf-8"))
    index["system"]["versions"].append(dict(index["system"]["versions"][1]))
    chemin.write_text(json.dumps(index), encoding="utf-8")

    assert any("double" in p for p in PromptStore(tmp_path).check())


def test_marque_page_vers_version_inexistante_detecte(store, tmp_path):
    chemin = tmp_path / INDEX_FILE
    index = json.loads(chemin.read_text(encoding="utf-8"))
    index["system"]["active"] = "v7"
    chemin.write_text(json.dumps(index), encoding="utf-8")

    assert any("v7" in p for p in PromptStore(tmp_path).check())
