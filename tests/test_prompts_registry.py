"""
Vérifie le registre de prompts réellement livré dans le dépôt — feature [A4].

Ce test tourne en CI : il échoue si quelqu'un modifie une version déjà rangée,
supprime un fichier de version, ou fusionne deux branches qui ont créé le même
numéro (ADR-0010). Pour corriger un prompt, on range une nouvelle version.
"""
from sensai.config import PROJECT_ROOT
from sensai.knowledge.prompt_versions import PromptStore


def test_registre_du_depot_coherent():
    store = PromptStore(PROJECT_ROOT / "prompts")

    assert store.exists()
    assert store.check() == []


def test_prompts_de_l_agent_versionnes():
    store = PromptStore(PROJECT_ROOT / "prompts")

    assert {"system", "memory"} <= set(store.names())
    assert store.load("system") != ""
    assert store.load("memory") != ""
