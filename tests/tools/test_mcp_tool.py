"""Teste le client MCP (T1, ADR-0041) contre un faux serveur stdio, sans réseau."""
import sys
from pathlib import Path

import pytest

from sensai.core.tools import ToolRegistry
from sensai.execution.gateway import ToolGateway
from sensai.execution.guardrails import filter_output
from sensai.execution.tool_policy import Risk, risk_of
from sensai.tools.mcp_tool import load_mcp_tools, parse_mcp_config

SERVER = str(Path(__file__).with_name("fake_mcp_server.py"))


def servers(mode="normal", **extra):
    return {"faux": {"command": sys.executable, "args": [SERVER, mode], **extra}}


@pytest.fixture
def loaded():
    tools, warnings, close = load_mcp_tools(parse_mcp_config(servers()))
    yield {t.name: t for t in tools}, warnings
    close()


def test_les_outils_du_serveur_deviennent_des_outils_de_l_agent(loaded):
    tools, warnings = loaded
    assert warnings == []
    assert set(tools) == {"mcp_faux_add", "mcp_faux_leak", "mcp_faux_fail", "mcp_faux_bad_name_"}
    add = tools["mcp_faux_add"]
    assert add.description.startswith("[MCP faux]") and "Additionne" in add.description
    assert add.parameters["required"] == ["a", "b"]
    assert tools["mcp_faux_bad_name_"].parameters == {"type": "object", "properties": {}}


def test_appel_d_un_outil_mcp(loaded):
    result = loaded[0]["mcp_faux_add"].run(a=2, b=3)
    assert result.ok and result.content == "5"


def test_erreur_signalee_par_le_serveur(loaded):
    result = loaded[0]["mcp_faux_fail"].run()
    assert not result.ok and "échec côté serveur" in result.content


def test_risque_execute_par_defaut_et_reglable():
    tools, _, close = load_mcp_tools(parse_mcp_config(servers()))
    assert all(risk_of(t) is Risk.EXECUTE for t in tools)
    close()
    tools, _, close = load_mcp_tools(parse_mcp_config(servers(risk="read")))
    assert all(risk_of(t) is Risk.READ for t in tools)
    close()


def test_la_passerelle_masque_les_secrets_renvoyes_par_le_serveur(loaded):
    registry = ToolRegistry()
    for tool in loaded[0].values():
        registry.register(tool)
    gateway = ToolGateway(registry, None, confirm=lambda request: True,
                          output_filters=[filter_output])
    result = gateway.call("mcp_faux_leak")
    assert "sk-abcdef1234567890abcdef" not in result.content


def test_serveur_introuvable_n_empeche_pas_le_demarrage():
    config = {"absent": {"command": "commande-qui-n-existe-pas-xyz"}, **servers()}
    tools, warnings, close = load_mcp_tools(parse_mcp_config(config))
    assert {t.name for t in tools} >= {"mcp_faux_add"}
    assert len(warnings) == 1 and "absent" in warnings[0]
    close()


@pytest.mark.parametrize("mode", ["silent", "garbage"])
def test_serveur_muet_ou_illisible_est_signale(mode):
    tools, warnings, close = load_mcp_tools(parse_mcp_config(servers(mode, timeout_s=2)))
    assert tools == [] and len(warnings) == 1 and "faux" in warnings[0]
    close()


def test_serveur_qui_plante_pendant_un_appel_rend_une_erreur_sans_lever():
    tools, _, close = load_mcp_tools(parse_mcp_config(servers("crash", timeout_s=3)))
    add = next(t for t in tools if t.name == "mcp_faux_add")
    result = add.run(a=1, b=2)
    assert not result.ok and "faux" in result.content
    assert not add.run(a=1, b=2).ok, "le suivant échoue proprement aussi"
    close()


@pytest.mark.parametrize("bad, message", [
    ({"x": {"args": []}}, "command"),
    ({"x": {"command": "a", "risk": "dangereux"}}, "risk"),
    ({"x": {"command": "a", "inconnu": 1}}, "inconnu"),
    ({"x y": {"command": "a"}}, "nom"),
    ([], "objet"),
])
def test_configuration_invalide_refusee(bad, message):
    with pytest.raises(ValueError, match=message):
        parse_mcp_config(bad)


def test_sans_configuration_aucun_serveur():
    assert parse_mcp_config(None) == {}
    tools, warnings, close = load_mcp_tools({})
    assert tools == [] and warnings == []
    close()


def test_la_confirmation_dit_quel_serveur_et_quels_arguments(loaded):
    text = loaded[0]["mcp_faux_add"].describe_call(a=2, b=3)
    assert "add" in text and "faux" in text and '"a": 2' in text
