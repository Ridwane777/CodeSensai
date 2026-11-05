"""
Teste le registre partagé par la CLI et le planificateur (X5).

`test_les_outils_du_lot_b_sont_proposes` échoue si un outil livré n'est plus
enregistré : c'est ce qui laissait l'agent sans `run_code` ni `read_file` en
conversation (essai réel du 2026-10-14).
"""
from sensai.execution.tool_policy import Risk, risk_of
from sensai.registry import build_registry


def test_les_outils_du_lot_b_sont_proposes():
    noms = {d["name"] for d in build_registry().describe_all()}

    assert {"run_code", "read_file", "write_file", "web_search"} <= noms


def test_chaque_outil_declare_son_risque():
    """Un risque absent est traité comme une exécution : on veut le vrai niveau."""
    registry = build_registry()
    risques = {d["name"]: risk_of(registry.get(d["name"])) for d in registry.describe_all()}

    assert risques["read_file"] is Risk.READ
    assert risques["write_file"] is Risk.WRITE
    assert risques["run_code"] is Risk.EXECUTE
    assert risques["web_search"] is Risk.NETWORK


def test_construire_le_registre_ne_lance_aucun_conteneur(monkeypatch):
    """Le CLI construit le registre au démarrage : Docker ne doit être contacté
    qu'au premier appel d'un outil, pas avant (CLI utilisable sans Docker)."""
    import sensai.execution.sandbox.docker_utils as docker_utils

    def interdit():
        raise AssertionError("Docker contacté à la construction du registre")

    monkeypatch.setattr(docker_utils, "connect", interdit)

    build_registry()
