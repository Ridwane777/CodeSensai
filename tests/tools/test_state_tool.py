"""
Teste l'outil `update_state` — feature [M4], ADR-0029.

`test_declare_le_risque_ecriture` protège A3 : sans lui, une injection de
prompt pourrait faire écrire l'agent dans SENSAI.md sans confirmation.
"""
from sensai.core.tools import ToolRegistry
from sensai.execution.gateway import ToolGateway
from sensai.execution.tool_policy import Risk, risk_of
from sensai.knowledge.state_document import StateDocument
from sensai.tools.state_tool import UpdateStateTool


def outil(tmp_path):
    projet = tmp_path / "projet"
    projet.mkdir()
    return UpdateStateTool(StateDocument(projet, tmp_path / "journal.jsonl"))


def test_declare_le_risque_ecriture(tmp_path):
    assert risk_of(outil(tmp_path)) is Risk.WRITE


def test_met_a_jour_et_renvoie_le_diff(tmp_path):
    t = outil(tmp_path)

    resultat = t.run(section="En cours", action="replace", content="- M4")

    assert resultat.ok
    assert "+- M4" in resultat.content
    assert "- M4" in t.document.path.read_text(encoding="utf-8")


def test_erreur_renvoyee_proprement_jamais_d_exception(tmp_path):
    t = outil(tmp_path)

    resultat = t.run(section="Roadmap", action="append", content="- x")

    assert not resultat.ok
    assert "En cours" in resultat.content


def test_la_confirmation_montre_l_avant_et_l_apres(tmp_path):
    """US-M4-3 : ce que l'utilisateur approuve, c'est le changement lui-même."""
    t = outil(tmp_path)
    t.run(section="En cours", action="replace", content="- R2")

    plan = t.describe_call(section="En cours", action="replace", content="- M4")

    assert "-- R2" in plan and "+- M4" in plan


def test_la_passerelle_demande_confirmation_et_un_refus_ne_change_rien(tmp_path):
    t = outil(tmp_path)
    registry = ToolRegistry()
    registry.register(t)
    demandes = []
    passerelle = ToolGateway(registry, confirm=lambda req: demandes.append(req) or False)

    resultat = passerelle.call("update_state", section="Fait", action="append", content="- x")

    assert len(demandes) == 1
    assert "+- x" in demandes[0].summary
    assert not resultat.ok
    assert not t.document.path.exists()
