"""
Teste le document d'état du projet — feature [M4], ADR-0029.

Le test qui porte la DoD est `test_les_autres_sections_restent_identiques_a_l_octet` :
il échoue si une mise à jour touche autre chose que la section visée, ce qui
reviendrait à « réécrire le document en entier ».
"""
import json

import pytest

from sensai.knowledge.state_document import (
    DEFAULT_SECTIONS,
    MAX_PROMPT_CHARS,
    STATE_FILE,
    StateDocument,
    StateError,
)

ECRIT_A_LA_MAIN = """# État du projet

Préambule écrit par l'humain.

## Fait

- Base Loop
- M1 : sessions

## En cours

- R2

## Décisions

- SQLite partout, pas de Postgres (voir ADR-0007).

## Problèmes connus

- L'indexation est lente sur le pod.

## Notes perso

Une section ajoutée à la main.
"""


@pytest.fixture
def doc(tmp_path):
    projet = tmp_path / "projet"
    projet.mkdir()
    return StateDocument(projet, tmp_path / "donnees" / "state" / "journal.jsonl")


def ecrire(doc, texte=ECRIT_A_LA_MAIN):
    doc.path.write_text(texte, encoding="utf-8")


# --- US-M4-1 : un fichier lisible, créé avec les sections de base --------------


def test_le_fichier_est_dans_le_projet(doc):
    assert doc.path.name == STATE_FILE == "SENSAI.md"
    assert doc.path.parent == doc.project


def test_premiere_mise_a_jour_cree_les_sections_de_base(doc):
    doc.update("En cours", "replace", "- M4 : document d'état")

    texte = doc.path.read_text(encoding="utf-8")
    for section in DEFAULT_SECTIONS:
        assert f"## {section}\n" in texte
    assert "- M4 : document d'état" in texte
    assert doc.sections() == list(DEFAULT_SECTIONS)


def test_sections_lues_dans_l_ordre_y_compris_celles_ajoutees_a_la_main(doc):
    ecrire(doc)

    assert doc.sections() == ["Fait", "En cours", "Décisions", "Problèmes connus", "Notes perso"]


# --- US-M4-2 : mise à jour ciblée, jamais destructrice ------------------------


def test_les_autres_sections_restent_identiques_a_l_octet(doc):
    ecrire(doc)
    avant = doc.path.read_text(encoding="utf-8")

    doc.update("En cours", "replace", "- M4\n- R2 (reranking)")

    apres = doc.path.read_text(encoding="utf-8")
    assert "- M4\n- R2 (reranking)" in apres
    assert "\n- R2\n" not in apres
    # Tout ce qui précède « ## En cours » et tout ce qui suit « ## Décisions » est intact.
    debut = avant.index("## En cours")
    suite = avant.index("## Décisions")
    assert apres.startswith(avant[:debut])
    assert apres.endswith(avant[suite:])


def test_append_ajoute_a_la_fin_de_la_section(doc):
    ecrire(doc)

    doc.update("Fait", "append", "- R1 : RAG")

    texte = doc.path.read_text(encoding="utf-8")
    assert "## Fait\n\n- Base Loop\n- M1 : sessions\n- R1 : RAG\n\n## En cours" in texte


def test_la_derniere_section_peut_etre_modifiee(doc):
    ecrire(doc)

    doc.update("Notes perso", "append", "Encore une note.")

    assert doc.path.read_text(encoding="utf-8").endswith(
        "Une section ajoutée à la main.\nEncore une note.\n"
    )


def test_section_inconnue_refusee_avec_la_liste_et_fichier_intact(doc):
    ecrire(doc)

    with pytest.raises(StateError) as erreur:
        doc.update("Roadmap", "append", "- X")

    assert "Fait" in str(erreur.value) and "En cours" in str(erreur.value)
    assert doc.path.read_text(encoding="utf-8") == ECRIT_A_LA_MAIN


@pytest.mark.parametrize("contenu", ["## Section cachée\n- x", "- ok\n# Titre", "  ## indenté"])
def test_un_titre_dans_le_contenu_est_refuse(doc, contenu):
    """Sinon le modèle pourrait créer une section ou casser le découpage."""
    ecrire(doc)

    with pytest.raises(StateError):
        doc.update("En cours", "replace", contenu)

    assert doc.path.read_text(encoding="utf-8") == ECRIT_A_LA_MAIN


def test_action_inconnue_refusee(doc):
    ecrire(doc)

    with pytest.raises(StateError):
        doc.update("En cours", "delete", "x")


def test_append_vide_refuse(doc):
    ecrire(doc)

    with pytest.raises(StateError):
        doc.update("Fait", "append", "   ")


def test_ecriture_interrompue_ne_laisse_pas_un_fichier_a_moitie_ecrit(doc, monkeypatch):
    ecrire(doc)
    import os

    def panne(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr(os, "replace", panne)

    with pytest.raises(OSError):
        doc.update("En cours", "replace", "- autre chose")

    assert doc.path.read_text(encoding="utf-8") == ECRIT_A_LA_MAIN
    assert [p.name for p in doc.project.iterdir()] == [STATE_FILE]


# --- US-M4-3 : voir, tracer, annuler ------------------------------------------


def test_preview_montre_la_section_avant_et_apres_sans_ecrire(doc):
    ecrire(doc)

    apercu = doc.preview("En cours", "replace", "- M4")

    assert "-- R2" in apercu or "- - R2" in apercu
    assert "+- M4" in apercu
    assert doc.path.read_text(encoding="utf-8") == ECRIT_A_LA_MAIN


def test_chaque_mise_a_jour_est_journalisee(doc):
    ecrire(doc)

    doc.update("En cours", "replace", "- M4", summary="M4 commencé")

    lignes = doc.journal_path.read_text(encoding="utf-8").splitlines()
    entree = json.loads(lignes[-1])
    assert entree["section"] == "En cours"
    assert entree["action"] == "replace"
    assert entree["before"].strip() == "- R2"
    assert entree["after"].strip() == "- M4"
    assert entree["summary"] == "M4 commencé"
    assert entree["date"]
    assert doc.history()[0]["section"] == "En cours"


def test_annuler_remet_la_section_dans_son_etat_precedent(doc):
    ecrire(doc)
    doc.update("En cours", "replace", "- M4")

    message = doc.undo("En cours")

    assert doc.path.read_text(encoding="utf-8") == ECRIT_A_LA_MAIN
    assert "En cours" in message
    assert doc.history()[0]["action"] == "undo"


def test_annuler_refuse_si_la_section_a_ete_modifiee_a_la_main(doc):
    ecrire(doc)
    doc.update("En cours", "replace", "- M4")
    texte = doc.path.read_text(encoding="utf-8").replace("- M4", "- M4 (corrigé à la main)")
    doc.path.write_text(texte, encoding="utf-8")

    with pytest.raises(StateError):
        doc.undo("En cours")

    assert "corrigé à la main" in doc.path.read_text(encoding="utf-8")


def test_annuler_sans_historique_refuse(doc):
    ecrire(doc)

    with pytest.raises(StateError):
        doc.undo("Fait")


def test_le_journal_est_propre_au_projet(tmp_path):
    a = StateDocument(tmp_path / "a", tmp_path / "journal-a.jsonl")
    b = StateDocument(tmp_path / "b", tmp_path / "journal-b.jsonl")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    a.update("Fait", "append", "- a")

    assert b.history() == []


# --- Prompt système (ADR-0029, décision 4) ------------------------------------


def test_sans_fichier_pas_de_prompt(doc):
    assert doc.as_prompt() == ""


def test_prompt_encadre_comme_une_donnee(doc):
    ecrire(doc)

    prompt = doc.as_prompt()

    assert "SENSAI.md" in prompt
    assert "- SQLite partout" in prompt
    assert "donnée" in prompt.lower() or "pas des instructions" in prompt.lower()


def test_prompt_tronque_au_dela_de_la_limite(doc):
    ecrire(doc, "## Fait\n\n" + "- tâche faite\n" * 2000)

    prompt = doc.as_prompt()

    assert len(prompt) <= MAX_PROMPT_CHARS + 500
    assert "tronqué" in prompt


def test_deux_annulations_remontent_de_deux_modifications(doc):
    """Comme Ctrl+Z (ADR-0029, choix fait après l'essai réel du 2026-10-17) :
    une annulation de plus remonte d'une modification de plus, elle n'annule
    pas l'annulation précédente."""
    ecrire(doc)
    doc.update("En cours", "replace", "- M4")
    doc.update("En cours", "replace", "- M4 et R2")

    doc.undo("En cours")
    assert "\n- M4\n" in doc.path.read_text(encoding="utf-8")

    doc.undo("En cours")
    assert doc.path.read_text(encoding="utf-8") == ECRIT_A_LA_MAIN

    with pytest.raises(StateError):
        doc.undo("En cours")


def test_une_nouvelle_modification_apres_annulation_repart_de_la(doc):
    ecrire(doc)
    doc.update("En cours", "replace", "- M4")
    doc.undo("En cours")
    doc.update("En cours", "replace", "- R2")

    doc.undo("En cours")

    assert doc.path.read_text(encoding="utf-8") == ECRIT_A_LA_MAIN
