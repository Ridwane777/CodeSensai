"""T4 permission layer: what it must refuse, and what it must still allow."""

import pytest

from sensai.execution.file_permissions import FilePermissions, PermissionDenied


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x")
    return tmp_path


def test_relative_path_inside_workspace_is_allowed(ws):
    perms = FilePermissions.for_workspace(ws)
    assert perms.check_read("src/a.py") == (ws / "src" / "a.py").resolve()


@pytest.mark.parametrize("bad", ["../outside.txt", "src/../../outside.txt", "/etc/passwd"])
def test_escape_is_refused(ws, bad):
    perms = FilePermissions.for_workspace(ws)
    with pytest.raises(PermissionDenied):
        perms.check_read(bad)
    with pytest.raises(PermissionDenied):
        perms.check_write(bad)


def test_symlink_pointing_outside_is_refused(ws, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("s")
    (ws / "link.txt").symlink_to(outside)
    with pytest.raises(PermissionDenied):
        FilePermissions.for_workspace(ws).check_read("link.txt")


@pytest.mark.parametrize(
    "name", [".env", ".env.local", ".git/config", "keys/server.pem", ".ssh/id_rsa", "Secrets.json"]
)
def test_sensitive_names_are_refused_even_inside_workspace(ws, name):
    perms = FilePermissions.for_workspace(ws)
    with pytest.raises(PermissionDenied):
        perms.check_read(name)
    with pytest.raises(PermissionDenied):
        perms.check_write(name)


def test_workspace_living_under_a_protected_looking_folder_stays_usable(tmp_path):
    root = tmp_path / "secrets-project"
    root.mkdir()
    assert FilePermissions.for_workspace(root).check_read("a.txt").name == "a.txt"


def test_read_and_write_roots_are_separate(ws):
    perms = FilePermissions.from_dict({"root": str(ws), "read": ["."], "write": ["src"]})
    perms.check_read("README.md")
    perms.check_write("src/new.py")
    with pytest.raises(PermissionDenied):
        perms.check_write("README.md")


def test_extra_deny_patterns_add_to_defaults_never_replace(ws):
    perms = FilePermissions.from_dict({"root": str(ws), "deny": ["*.sql"]})
    with pytest.raises(PermissionDenied):
        perms.check_read("dump.sql")
    with pytest.raises(PermissionDenied):
        perms.check_read(".env")


def test_unknown_setting_is_an_error(ws):
    with pytest.raises(ValueError):
        FilePermissions.from_dict({"root": str(ws), "allow_everything": True})


@pytest.mark.parametrize("bad", ["", "   ", "a\x00b"])
def test_empty_or_null_path_is_refused(ws, bad):
    with pytest.raises(PermissionDenied):
        FilePermissions.for_workspace(ws).check_read(bad)
