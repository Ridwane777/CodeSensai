"""
[Lot B] write_file — creates or replaces a text file inside the allowed
folders — feature [T4].

Risk `write`: the gateway always asks first, and what the user approves is
`describe_call`: the exact path and, when replacing, a diff. By default the
tool refuses to overwrite an existing file: replacing needs `overwrite=true`,
which is visible in the confirmation.
"""

from __future__ import annotations

import difflib
import os
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.execution.file_permissions import FilePermissions, PermissionDenied

_DIFF_LINES = 60  # enough to judge a change, short enough to read in a terminal


class WriteFileTool:
    name = "write_file"
    description = (
        "Create a text file in the project, or replace one with overwrite=true. "
        "Parent folders are created. Without overwrite=true an existing file is "
        "never touched. The user must approve every write. Paths are relative to "
        "the project root; secrets (.env, keys, .git) are refused."
    )
    risk = "write"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the project."},
            "content": {"type": "string", "description": "Full new content of the file."},
            "overwrite": {"type": "boolean", "description": "Allow replacing an existing file."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(self, permissions: FilePermissions | None = None) -> None:
        self.permissions = permissions or FilePermissions.for_workspace()

    def describe_call(self, **args: Any) -> str:
        """What the user approves: where, create or replace, and the change itself."""
        content = args.get("content", "")
        try:
            path = self.permissions.check_write(args.get("path", ""))
        except PermissionDenied as exc:
            return f"Write {args.get('path')!r} — will be refused: {exc}"
        size = len(content.encode("utf-8"))
        if not path.exists():
            return f"CREATE {path} ({size} bytes):\n\n{_clip(content)}"
        if not args.get("overwrite"):
            return f"Write {path} — will be refused: it already exists and overwrite is not set."
        try:
            before = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeDecodeError):
            return f"REPLACE {path} (existing content not readable as text) with {size} bytes."
        diff = list(
            difflib.unified_diff(
                before, content.splitlines(keepends=True), "before", "after", lineterm=""
            )
        )
        shown = "".join(f"{line}\n" if not line.endswith("\n") else line for line in diff)
        return f"REPLACE {path} ({size} bytes). Changes:\n\n{_clip(shown) or '(identical content)'}"

    def run(self, **kwargs: Any) -> ToolResult:
        content = kwargs.get("content", "")
        try:
            path = self.permissions.check_write(kwargs.get("path", ""))
        except PermissionDenied as exc:
            return ToolResult(ok=False, content=str(exc), data={"error": "permission_denied"})
        size = len(content.encode("utf-8"))
        max_bytes = self.permissions.max_write_bytes
        if size > max_bytes:
            return ToolResult(
                ok=False,
                content=f"Content is {size} bytes, over the {max_bytes} limit.",
                data={"error": "too_large"},
            )
        if path.is_dir():
            return ToolResult(
                ok=False, content=f"{path.name} is a folder.", data={"error": "is_dir"}
            )
        existed = path.exists()
        if existed and not kwargs.get("overwrite"):
            return ToolResult(
                ok=False,
                content=f"{path.name} already exists. Use overwrite=true to replace it.",
                data={"error": "exists"},
            )
        try:
            _write_atomic(path, content)
        except OSError as exc:
            return ToolResult(
                ok=False, content=f"Cannot write: {exc.strerror}", data={"error": "io"}
            )
        verb = "Replaced" if existed else "Created"
        return ToolResult(
            ok=True,
            content=f"{verb} {path} ({size} bytes).",
            data={"path": str(path), "bytes": size, "created": not existed},
        )


def _clip(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= _DIFF_LINES:
        return text
    return "\n".join(lines[:_DIFF_LINES]) + f"\n[... {len(lines) - _DIFF_LINES} more lines ...]"


def _write_atomic(path: Path, content: str) -> None:
    """Write to a temp file in the same folder, then rename: no half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
