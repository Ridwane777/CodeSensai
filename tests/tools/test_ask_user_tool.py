"""
L'outil `ask_user` (X4, ADR-0046) : validation du formulaire, des réponses, et
version terminal. Le parcours web est dans tests/web/test_questions.py.
"""
import json

import pytest

from sensai.tools.ask_user_tool import (
    MAX_FIELDS,
    AskUserTool,
    FormError,
    check_answers,
    parse_question,
    terminal_asker,
)

FIELDS = [
    {"id": "nom", "kind": "text", "label": "Nom du module"},
    {"id": "style", "kind": "choice", "label": "Style", "options": ["pytest", "unittest"]},
    {"id": "docs", "kind": "toggle", "label": "Ajouter la doc ?"},
]


def test_un_formulaire_valide_est_accepte():
    q = parse_question("Quelques précisions", FIELDS)
    assert q.title == "Quelques précisions"
    assert [f["kind"] for f in q.fields] == ["text", "choice", "toggle"]


def test_le_type_par_defaut_est_un_texte():
    q = parse_question("?", [{"id": "a", "label": "A"}])
    assert q.fields[0]["kind"] == "text"


@pytest.mark.parametrize("title, fields", [
    ("", FIELDS),
    ("?", []),
    ("?", "pas une liste"),
    ("?", [{"id": "a", "label": "A"}] * 2),  # identifiant en double
    ("?", [{"id": "a", "kind": "date", "label": "A"}]),
    ("?", [{"id": "a", "kind": "choice", "label": "A", "options": ["seul"]}]),
    ("?", [{"id": "a", "kind": "choice", "label": "A", "options": ["x", "x"]}]),
    ("?", [{"id": "a", "label": ""}]),
    ("?", [{"id": f"f{i}", "label": "L"} for i in range(MAX_FIELDS + 1)]),
    ("x" * 201, FIELDS),
])
def test_un_formulaire_invalide_est_refuse(title, fields):
    with pytest.raises(FormError):
        parse_question(title, fields)


def test_des_reponses_valides_sont_acceptees():
    q = parse_question("?", FIELDS)
    values = {"nom": " outils ", "style": "pytest", "docs": False}
    assert check_answers(q, values) == {"nom": "outils", "style": "pytest", "docs": False}


@pytest.mark.parametrize("values", [
    {"nom": "a", "style": "pytest"},                       # réponse manquante
    {"nom": "a", "style": "pytest", "docs": True, "x": 1},  # champ inconnu
    {"nom": "a", "style": "nose", "docs": True},           # choix absent
    {"nom": "a", "style": "pytest", "docs": "oui"},        # pas un booléen
    {"nom": "  ", "style": "pytest", "docs": True},        # texte vide
    {"nom": 3, "style": "pytest", "docs": True},           # pas un texte
    ["pas", "un", "objet"],
])
def test_des_reponses_invalides_sont_refusees(values):
    with pytest.raises(FormError):
        check_answers(parse_question("?", FIELDS), values)


def test_l_outil_renvoie_les_reponses_au_modele():
    tool = AskUserTool(lambda q: {"nom": "outils"})
    result = tool.run(title="?", fields=[{"id": "nom", "label": "Nom"}])
    assert result.ok
    assert json.loads(result.content.split(" : ", 1)[1]) == {"nom": "outils"}


def test_sans_reponse_l_outil_echoue_et_le_dit():
    result = AskUserTool(lambda q: None).run(title="?", fields=[{"id": "a", "label": "A"}])
    assert not result.ok and "pas répondu" in result.content


def test_sans_interface_personne_ne_peut_repondre():
    result = AskUserTool(None).run(title="?", fields=[{"id": "a", "label": "A"}])
    assert not result.ok and "Aucune personne" in result.content


def test_un_formulaire_invalide_ne_sollicite_personne():
    asked = []
    result = AskUserTool(asked.append).run(title="?", fields=[])
    assert not result.ok and "Formulaire invalide" in result.content and asked == []


def test_le_terminal_pose_chaque_question():
    # Un texte vide puis un mauvais numéro : redemandés.
    answers = iter(["", "outils", "9", "2", "o"])
    shown = []
    ask = terminal_asker(read=lambda prompt: next(answers), show=shown.append)
    values = ask(parse_question("Précisions", FIELDS))
    assert values == {"nom": "outils", "style": "unittest", "docs": True}
    assert any("Précisions" in line for line in shown)


def test_ctrl_d_dans_le_terminal_c_est_pas_de_reponse():
    def eof(prompt):
        raise EOFError
    assert terminal_asker(read=eof, show=lambda s: None)(parse_question("?", FIELDS)) is None
