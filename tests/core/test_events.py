"""
Teste le contrat entre le cœur et les interfaces (ADR-0005).

Ces tests protègent ce sur quoi la CLI et l'interface web s'accordent : les
noms transmis sur le réseau et la garantie qu'un tour se termine toujours
par Done. Les casser, c'est casser le Lot D sans s'en rendre compte.
"""
import pytest

from sensai.cli import describe_request, render
from sensai.core.events import Done, Error, Thought, Token, ToolCall, ToolReturn, to_wire
from sensai.execution.gateway import ConfirmationRequest
from sensai.execution.tool_policy import Risk


def test_les_noms_reseau_sont_stables():
    """L'interface web lit ces chaînes. Les changer casse son code."""
    assert to_wire(Token(text="a"))["type"] == "token"
    assert to_wire(Thought(text="a"))["type"] == "thought"
    assert to_wire(ToolCall(id="1", name="echo"))["type"] == "tool_call"
    assert to_wire(ToolReturn(id="1", name="echo", ok=True, content="a"))["type"] == "tool_return"
    assert to_wire(Error(message="a"))["type"] == "error"
    assert to_wire(Done())["type"] == "done"


def test_les_champs_partent_avec_l_evenement():
    wire = to_wire(ToolCall(id="42", name="run_code", arguments={"code": "print(1)"}))

    assert wire == {
        "type": "tool_call",
        "id": "42",
        "name": "run_code",
        "arguments": {"code": "print(1)"},
    }


def test_un_appel_et_son_resultat_partagent_le_meme_id():
    """Sans cet identifiant, deux outils qui s'enchaînent ne sont plus
    rattachables l'un à l'autre côté interface."""
    appel = ToolCall(id="7", name="echo", arguments={"text": "x"})
    retour = ToolReturn(id="7", name="echo", ok=True, content="x")

    assert to_wire(appel)["id"] == to_wire(retour)["id"]


def test_un_objet_qui_n_est_pas_un_evenement_est_refuse():
    """Mieux vaut échouer ici qu'envoyer au navigateur un JSON qu'il ne sait
    pas lire."""
    with pytest.raises(TypeError):
        to_wire("juste du texte")


def test_done_par_defaut_est_une_reponse_finale():
    assert Done().reason == "final_answer"


def test_la_cli_affiche_chaque_evenement():
    """Le rendu terminal et le rendu web partent des mêmes événements : si un
    type n'est pas traité ici, c'est qu'il manquera aussi côté web."""
    assert render(Token(text="salut")) == "salut"
    assert "réflexion" in render(Thought(text="réflexion"))
    assert "run_code" in render(ToolCall(id="1", name="run_code"))
    assert "✓" in render(ToolReturn(id="1", name="echo", ok=True, content="ok"))
    assert "✗" in render(ToolReturn(id="1", name="echo", ok=False, content="raté"))
    assert "Erreur" in render(Error(message="Ollama injoignable"))
    assert render(Done()) == ""


def test_un_arret_sur_max_iterations_est_signale():
    """Sinon un tour coupé s'affiche comme une réponse vide."""
    assert "maximal" in render(Done(reason="max_iterations"))


def test_la_confirmation_montre_le_code_en_clair():
    """Le résumé JSON de la passerelle échapperait les retours à la ligne :
    on doit approuver le code tel qu'il sera exécuté."""
    request = ConfirmationRequest(
        tool="run_code",
        risk=Risk.EXECUTE,
        summary="",
        arguments={"code": "import os\nos.listdir()"},
        timeout_s=1,
    )

    assert "import os\nos.listdir()" in describe_request(request)


def test_la_confirmation_montre_le_plan_de_l_outil_quand_il_en_donne_un():
    """Un outil qui fournit `describe_call` (write_file, update_state) montre le
    changement lui-même : c'est ce que l'utilisateur approuve (US-M4-3)."""
    request = ConfirmationRequest(
        tool="update_state",
        risk=Risk.WRITE,
        summary="SENSAI.md, section « En cours » :\n--- avant\n+++ après\n-- R2\n+- M4",
        arguments={"section": "En cours", "action": "replace", "content": "- M4"},
        timeout_s=1,
    )

    texte = describe_request(request)

    assert "-- R2" in texte and "+- M4" in texte
