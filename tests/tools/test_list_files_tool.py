"""list_files (ADR-0059) : voir les fichiers du projet, mêmes règles que read_file."""

import subprocess

import pytest

from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.gateway import ToolGateway
from sensai.registry import build_registry
from sensai.tools import list_files_tool
from sensai.tools.list_files_tool import ListFilesTool


@pytest.fixture
def projet(tmp_path):
    (tmp_path / "stats.py").write_text("def moyenne(n): ...\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_stats.py").write_text("def test(): ...\n")
    (tmp_path / ".env").write_text("CLE=secret\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("x\n")
    return tmp_path


def lister(projet, **kwargs):
    return ListFilesTool(FilePermissions.for_workspace(projet)).run(**kwargs)


def test_l_outil_est_en_lecture_seule_et_dans_le_registre():
    assert ListFilesTool.risk == "read"
    assert "list_files" in [d["name"] for d in build_registry().describe_all()]


def test_liste_les_fichiers_du_projet_sans_secrets_ni_dependances(projet):
    result = lister(projet)
    assert result.ok
    assert result.content.splitlines() == ["stats.py", "tests/test_stats.py"]
    assert ".env" not in result.content and "node_modules" not in result.content


def test_un_sous_dossier(projet):
    assert lister(projet, path="tests").content == "tests/test_stats.py"


def test_respecte_le_gitignore_d_un_depot(projet):
    subprocess.run(["git", "init", "-q", str(projet)], check=True)
    (projet / ".gitignore").write_text("build/\n")
    (projet / "build").mkdir()
    (projet / "build" / "out.py").write_text("x\n")
    assert "build/out.py" not in lister(projet).content


def test_refuse_hors_du_projet_et_un_nom_protege(projet):
    assert not lister(projet, path="..").ok
    assert not lister(projet, path=".git").ok
    assert lister(projet, path="stats.py").data["error"] == "not_found"


def test_coupe_au_plafond_et_le_dit(projet, monkeypatch):
    monkeypatch.setattr(list_files_tool, "MAX_ENTRIES", 1)
    result = lister(projet)
    assert result.data == {"count": 2, "returned": 1}
    assert "1 more files" in result.content


def test_passe_par_la_passerelle_sans_confirmation(projet):
    registry = ToolRegistry()
    registry.register(ListFilesTool(FilePermissions.for_workspace(projet)))
    demandes = []
    gateway = ToolGateway(registry, confirm=lambda req: demandes.append(req) or True)
    assert gateway.call("list_files").ok
    assert demandes == []
