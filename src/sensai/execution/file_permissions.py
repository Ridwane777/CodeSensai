"""
Permission layer for file access — feature [T4].

Every path an agent gives to a file tool goes through here BEFORE any
filesystem call. The rules, in order:

1. The path is resolved (relative paths start from the workspace root,
   ``..`` and symlinks are followed) and must end up inside an allowed root.
   Checking the resolved path, not the text, is what stops ``../../etc/passwd``
   and a symlink pointing out of the workspace.
2. It must not be a sensitive file (credentials, keys, ``.git`` internals),
   even inside an allowed root.
3. Reads and writes have separate roots: a project can be readable and only
   ``src/`` writable.

Default: the workspace root (the current directory) for both. Nothing outside
is reachable unless the user lists it. Deny wins over allow.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

# Matched against each part of the resolved path, case-insensitively.
DEFAULT_DENY: tuple[str, ...] = (
    ".git",
    ".ssh",
    ".aws",
    ".gnupg",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials*",
    "secrets*",
)

DEFAULT_MAX_READ_BYTES = 1_000_000
DEFAULT_MAX_WRITE_BYTES = 1_000_000


class PermissionDenied(Exception):
    """The path is not allowed. The message says why, so the model can adapt."""


@dataclass(frozen=True)
class FilePermissions:
    root: Path
    read_roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]
    deny: tuple[str, ...] = DEFAULT_DENY
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES
    max_write_bytes: int = DEFAULT_MAX_WRITE_BYTES

    @classmethod
    def for_workspace(cls, root: str | Path | None = None, **kwargs: Any) -> FilePermissions:
        base = Path(root or Path.cwd()).resolve()
        return cls(root=base, read_roots=(base,), write_roots=(base,), **kwargs)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> FilePermissions:
        """Build from the ``files`` section of the config; unknown keys are an error."""
        raw = dict(raw or {})
        known = {"root", "read", "write", "deny", "max_read_bytes", "max_write_bytes"}
        if unknown := set(raw) - known:
            raise ValueError(f"unknown files settings: {sorted(unknown)}")
        root = Path(raw.get("root") or Path.cwd()).resolve()

        def roots(key: str) -> tuple[Path, ...]:
            return tuple(
                (root / p).resolve() for p in raw.get(key, ["."])
            )  # absolute entries replace root: Path semantics

        kwargs: dict[str, Any] = {}
        if "deny" in raw:
            # Extra patterns add to the defaults: the list can only grow.
            kwargs["deny"] = DEFAULT_DENY + tuple(raw["deny"])
        for key in ("max_read_bytes", "max_write_bytes"):
            if key in raw:
                kwargs[key] = int(raw[key])
        return cls(root=root, read_roots=roots("read"), write_roots=roots("write"), **kwargs)

    # -- checks ------------------------------------------------------------

    def resolve(self, path: str) -> Path:
        if not isinstance(path, str) or not path.strip():
            raise PermissionDenied("path is empty")
        if "\x00" in path:
            raise PermissionDenied("path contains a null byte")
        try:
            return (self.root / Path(path).expanduser()).resolve()
        except (OSError, RuntimeError) as exc:  # symlink loop, unreadable component
            raise PermissionDenied(f"cannot resolve path: {exc}") from exc

    def check_read(self, path: str) -> Path:
        return self._check(path, self.read_roots, "read")

    def check_write(self, path: str) -> Path:
        return self._check(path, self.write_roots, "write")

    def _check(self, path: str, roots: Iterable[Path], action: str) -> Path:
        resolved = self.resolve(path)
        if not any(resolved.is_relative_to(r) for r in roots):
            allowed = ", ".join(str(r) for r in roots) or "(none)"
            raise PermissionDenied(
                f"{action} access outside the allowed folders. Allowed: {allowed}"
            )
        if (hit := self._denied_part(resolved)) is not None:
            raise PermissionDenied(f"{hit!r} is a protected name: {action} refused")
        return resolved

    def _denied_part(self, resolved: Path) -> str | None:
        # Only the parts below the allowed root count: a workspace that itself
        # lives under ".../secrets-project/" must stay usable.
        base = next(
            (r for r in (*self.read_roots, *self.write_roots) if resolved.is_relative_to(r)),
            self.root,
        )
        for part in resolved.relative_to(base).parts:
            if any(fnmatch(part.lower(), pattern.lower()) for pattern in self.deny):
                return part
        return None
