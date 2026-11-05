"""read_file / write_file, alone and through the real gateway."""

import pytest

from sensai.core.tools import ToolRegistry
from sensai.execution import gateway as gw
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.gateway import ToolGateway
from sensai.tools.read_file_tool import ReadFileTool
from sensai.tools.write_file_tool import WriteFileTool


@pytest.fixture
def perms(tmp_path):
    return FilePermissions.for_workspace(tmp_path)


def gateway(perms, confirm=lambda req: True):
    registry = ToolRegistry()
    registry.register(ReadFileTool(perms))
    registry.register(WriteFileTool(perms))
    return ToolGateway(registry, confirm=confirm)


# --- read_file ---------------------------------------------------------------


def test_declared_risks():
    assert ReadFileTool.risk == "read"
    assert WriteFileTool.risk == "write"


def test_read_returns_content(perms, tmp_path):
    (tmp_path / "a.txt").write_text("un\ndeux\n")
    result = ReadFileTool(perms).run(path="a.txt")
    assert result.ok and result.content == "un\ndeux"


def test_read_pages_long_files(perms, tmp_path):
    (tmp_path / "big.txt").write_text("\n".join(f"l{i}" for i in range(1, 11)))
    first = ReadFileTool(perms).run(path="big.txt", limit=4)
    assert first.content.startswith("l1\nl2\nl3\nl4") and "offset=5" in first.content
    rest = ReadFileTool(perms).run(path="big.txt", offset=9, limit=4)
    assert rest.content == "l9\nl10"


@pytest.mark.parametrize(
    "setup, code",
    [
        (lambda p: None, "not_found"),
        (lambda p: (p / "d").mkdir(), "not_found"),
        (lambda p: (p / "b.bin").write_bytes(b"\xff\xfe\x00\x80"), "not_text"),
    ],
)
def test_read_failures_are_results_not_exceptions(perms, tmp_path, setup, code):
    setup(tmp_path)
    name = {"not_text": "b.bin"}.get(code, "d" if (tmp_path / "d").exists() else "missing.txt")
    result = ReadFileTool(perms).run(path=name)
    assert not result.ok and result.data["error"] == code


def test_read_too_large(tmp_path):
    perms = FilePermissions.for_workspace(tmp_path, max_read_bytes=10)
    (tmp_path / "x.txt").write_text("x" * 50)
    assert ReadFileTool(perms).run(path="x.txt").data["error"] == "too_large"


def test_read_refuses_secrets_and_escapes(perms, tmp_path):
    (tmp_path / ".env").write_text("KEY=1")
    for path in (".env", "../x", "/etc/passwd"):
        result = ReadFileTool(perms).run(path=path)
        assert not result.ok and result.data["error"] == "permission_denied"


# --- write_file --------------------------------------------------------------


def test_write_creates_file_and_parents(perms, tmp_path):
    result = WriteFileTool(perms).run(path="pkg/mod.py", content="print(1)\n")
    assert result.ok and result.data["created"] is True
    assert (tmp_path / "pkg" / "mod.py").read_text() == "print(1)\n"


def test_write_never_overwrites_by_default(perms, tmp_path):
    (tmp_path / "a.txt").write_text("old")
    result = WriteFileTool(perms).run(path="a.txt", content="new")
    assert result.data["error"] == "exists"
    assert (tmp_path / "a.txt").read_text() == "old"


def test_overwrite_replaces_and_leaves_no_temp_file(perms, tmp_path):
    (tmp_path / "a.txt").write_text("old")
    result = WriteFileTool(perms).run(path="a.txt", content="new", overwrite=True)
    assert result.ok and result.data["created"] is False
    assert (tmp_path / "a.txt").read_text() == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["a.txt"]


def test_write_refuses_secrets_escapes_and_folders(perms, tmp_path):
    (tmp_path / "d").mkdir()
    for path, code in (
        (".env", "permission_denied"),
        ("../x", "permission_denied"),
        ("d", "is_dir"),
    ):
        assert WriteFileTool(perms).run(path=path, content="x").data["error"] == code
    assert not (tmp_path.parent / "x").exists()


def test_write_too_large(tmp_path):
    perms = FilePermissions.for_workspace(tmp_path, max_write_bytes=5)
    assert WriteFileTool(perms).run(path="a", content="123456").data["error"] == "too_large"


def test_describe_call_shows_a_diff_when_replacing(perms, tmp_path):
    (tmp_path / "a.txt").write_text("alpha\nbeta\n")
    text = WriteFileTool(perms).describe_call(
        path="a.txt", content="alpha\ngamma\n", overwrite=True
    )
    assert "REPLACE" in text and "-beta" in text and "+gamma" in text


def test_describe_call_says_create_and_warns_when_it_will_be_refused(perms, tmp_path):
    tool = WriteFileTool(perms)
    assert tool.describe_call(path="new.txt", content="hi").startswith("CREATE")
    assert "will be refused" in tool.describe_call(path=".env", content="x")


# --- through the gateway -----------------------------------------------------


def test_nothing_is_written_without_confirmation(perms, tmp_path):
    result = gateway(perms, confirm=lambda req: False).call("write_file", path="a.txt", content="x")
    assert result.data["error"] == gw.REFUSED and not (tmp_path / "a.txt").exists()


def test_default_confirmer_refuses_writes(perms, tmp_path):
    registry = ToolRegistry()
    registry.register(WriteFileTool(perms))
    result = ToolGateway(registry).call("write_file", path="a.txt", content="x")
    assert result.data["error"] == gw.REFUSED and not (tmp_path / "a.txt").exists()


def test_user_is_shown_the_target_path_before_approving(perms, tmp_path):
    seen = []
    gateway(perms, confirm=lambda req: seen.append(req.summary) or True).call(
        "write_file", path="a.txt", content="x"
    )
    assert str(tmp_path / "a.txt") in seen[0]


def test_read_runs_without_asking(perms, tmp_path):
    (tmp_path / "a.txt").write_text("ok")
    result = gateway(perms, confirm=lambda req: pytest.fail("must not ask")).call(
        "read_file", path="a.txt"
    )
    assert result.ok
