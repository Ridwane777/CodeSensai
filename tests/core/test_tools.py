"""
Teste le contrat Tool + le ToolRegistry — indépendamment de l'agent, du
sandbox ou du RAG. Sert de modèle pour les tests que Méric et Ridwane
écriront pour leurs propres outils.
"""
from sensai.core.tools import ToolRegistry
from sensai.tools.echo_tool import EchoTool


def test_register_and_call():
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = registry.call("echo", text="bonjour")

    assert result.ok is True
    assert result.content == "bonjour"


def test_unknown_tool_does_not_crash():
    registry = ToolRegistry()

    result = registry.call("outil_qui_n_existe_pas", text="peu importe")

    assert result.ok is False
    assert "inconnu" in result.content.lower()


def test_describe_all_lists_registered_tools():
    registry = ToolRegistry()
    registry.register(EchoTool())

    descriptions = registry.describe_all()

    assert len(descriptions) == 1
    assert descriptions[0]["name"] == "echo"


def test_un_parametre_nomme_name_ne_casse_pas_l_appel():
    """Le registre prend déjà un argument `name` (le nom de l'outil) : il ne
    doit pas entrer en conflit avec un paramètre d'outil du même nom."""
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = registry.call("echo", text="x", name="conflit")

    assert result.ok is True
