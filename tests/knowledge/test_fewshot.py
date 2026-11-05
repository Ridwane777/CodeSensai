"""
Teste la sélection d'exemples few-shot — feature [A7], ADR-0044.

Même `FauxEmbedder` (sac de mots haché) que `test_rag.py` : deux questions
qui partagent des mots ont des vecteurs proches, ce qui suffit à tester la
recherche sans Ollama.
"""
import pytest

from sensai.eval.dataset import DatasetError
from sensai.knowledge.fewshot import Example, FewShotError, FewShotIndex, format_example
from tests.knowledge.test_rag import FauxEmbedder


@pytest.fixture
def exemples(tmp_path):
    path = tmp_path / "exemples.jsonl"
    path.write_text(
        '{"id": "1", "question": "Explique la fonction verifier_token",'
        ' "answer": "Elle compare le jeton reçu au secret attendu."}\n'
        '{"id": "2", "question": "Comment fonctionne le cache de réponses ?",'
        ' "answer": "Il sert la réponse déjà calculée pour une question proche."}\n'
        '{"id": "3", "question": "Cas sans réponse",'
        ' "notes": "ignoré : pas de answer"}\n',
        encoding="utf-8",
    )
    return path


def test_charge_seulement_les_cas_avec_une_reponse(exemples):
    index = FewShotIndex(FauxEmbedder())
    assert index.load(str(exemples)) == 2


def test_fichier_sans_aucun_cas_utilisable_refuse(tmp_path):
    path = tmp_path / "vide.jsonl"
    path.write_text('{"id": "1", "question": "Sans réponse"}\n', encoding="utf-8")
    index = FewShotIndex(FauxEmbedder())
    with pytest.raises(FewShotError, match="answer"):
        index.load(str(path))


def test_fichier_illisible_leve_fewshoterror(tmp_path):
    index = FewShotIndex(FauxEmbedder())
    with pytest.raises(FewShotError):
        index.load(str(tmp_path / "absent.jsonl"))


def test_fichier_mal_forme_leve_fewshoterror(tmp_path):
    path = tmp_path / "mauvais.jsonl"
    path.write_text("pas du json\n", encoding="utf-8")
    index = FewShotIndex(FauxEmbedder())
    with pytest.raises(FewShotError):
        index.load(str(path))


def test_erreur_de_chargement_garde_le_message_de_la_dataset_error(exemples, monkeypatch):
    """FewShotError enveloppe DatasetError, elle ne la remplace pas en silence."""
    import sensai.knowledge.fewshot as fewshot_module

    def _echoue(path):
        raise DatasetError("ligne 1 : cassé")

    monkeypatch.setattr(fewshot_module, "load_dataset", _echoue)
    index = FewShotIndex(FauxEmbedder())
    with pytest.raises(FewShotError, match="cassé"):
        index.load(str(exemples))


def test_best_match_trouve_lexemple_le_plus_proche(exemples):
    index = FewShotIndex(FauxEmbedder(), min_score=0.1)
    index.load(str(exemples))

    best = index.best_match("Comment marche la fonction verifier_token ?")
    assert best is not None
    assert best.question == "Explique la fonction verifier_token"


def test_best_match_sous_le_seuil_retourne_none(exemples):
    index = FewShotIndex(FauxEmbedder(), min_score=0.99)
    index.load(str(exemples))

    assert index.best_match("Une question sans aucun rapport") is None


def test_best_match_sans_index_charge_retourne_none():
    index = FewShotIndex(FauxEmbedder())
    assert index.best_match("peu importe") is None


def test_format_example_contient_question_et_reponse_sans_repondre_a_sa_place():
    texte = format_example(Example(question="Q ?", answer="R."))
    assert "Q ?" in texte
    assert "R." in texte
    assert "ne réponds pas à cet exemple" in texte


def test_l_exemple_cede_la_place_aux_preferences_de_l_utilisateur():
    """Essai réel du 2026-11-01 : un exemple en français l'a emporté sur « réponds en anglais »."""
    from sensai.knowledge.fewshot import Example, format_example

    text = format_example(Example(question="Comment lancer les tests ?", answer="pytest -q"))
    assert "préférences de l'utilisateur" in text and "passent avant" in text


def test_les_preferences_sont_rappelees_a_cote_de_l_exemple():
    """Essai réel du 2026-11-01 : dans le prompt système seulement, « réponds en
    anglais » perdait contre un exemple en français, trois fois sur trois."""
    text = format_example(Example(question="Q ?", answer="R."), ["Réponds toujours en anglais."])
    assert text.rstrip().endswith("Réponds toujours en anglais.]")
    sans = format_example(Example(question="Q ?", answer="R."))
    assert "Préférences" not in sans.split("]\n", 1)[1]


def test_l_exemple_identique_n_est_pas_joint_quand_il_y_a_des_preferences():
    """Essai réel du 2026-11-01 après-midi : la question de l'exemple, mot pour mot,
    recevait sa réponse en français malgré « réponds en anglais »."""
    from sensai.knowledge.fewshot import worth_attaching

    ex = Example(question="Comment lancer les tests du projet ?", answer="pytest -q")
    prefs = ["Réponds toujours en anglais."]
    assert not worth_attaching(ex, "comment lancer les tests du projet", prefs)
    assert worth_attaching(ex, "Comment lancer les tests du projet ?")
    assert worth_attaching(ex, "Quelle commande lance les tests ?", prefs)
