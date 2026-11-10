"""list_files (ADR-0059): seeing the project files, same rules as read_file."""

import subprocess

import pytest

from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.gateway import ToolGateway
from sensai.registry import build_registry
from sensai.tools import list_files_tool
from sensai.tools.list_files_tool import ListFilesTool


@pytest.fixture
def project(tmp_path):
    (tmp_path / "stats.py").write_text("def mean(n): ...\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_stats.py").write_text("def test(): ...\n")
    (tmp_path / ".env").write_text("KEY=secret\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("x\n")
    return tmp_path


def list_(project, **kwargs):
    return ListFilesTool(FilePermissions.for_workspace(project)).run(**kwargs)


def test_the_tool_is_read_only_and_in_the_registry():
    assert ListFilesTool.risk == "read"
    assert "list_files" in [d["name"] for d in build_registry().describe_all()]


def test_lists_project_files_without_secrets_or_dependencies(project):
    result = list_(project)
    assert result.ok
    assert result.content.splitlines() == ["stats.py", "tests/test_stats.py"]
    assert ".env" not in result.content and "node_modules" not in result.content


def test_a_subfolder(project):
    assert list_(project, path="tests").content == "tests/test_stats.py"


def test_respects_a_repository_gitignore(project):
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text("build/\n")
    (project / "build").mkdir()
    (project / "build" / "out.py").write_text("x\n")
    assert "build/out.py" not in list_(project).content


def test_refuses_outside_the_project_and_a_protected_name(project):
    assert not list_(project, path="..").ok
    assert not list_(project, path=".git").ok
    assert list_(project, path="stats.py").data["error"] == "not_found"


def test_truncates_at_the_cap_and_says_so(project, monkeypatch):
    monkeypatch.setattr(list_files_tool, "MAX_ENTRIES", 1)
    result = list_(project)
    assert result.data == {"count": 2, "returned": 1}
    assert "1 more files" in result.content


def test_goes_through_the_gateway_without_confirmation(project):
    registry = ToolRegistry()
    registry.register(ListFilesTool(FilePermissions.for_workspace(project)))
    requests = []
    gateway = ToolGateway(registry, confirm=lambda req: requests.append(req) or True)
    assert gateway.call("list_files").ok
    assert requests == []
