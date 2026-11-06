"""
list_files — lists the project's files, read-only — feature [T4], ADR-0059.

Without it the agent could not see which files exist when RAG is off: in the
trial of 2026-11-06 it guessed `main.py`, `src/utils.py`… and never found
`stats.py` (backlog #25). The listing follows the same rules as read_file
(execution.file_permissions: allowed folders, protected names such as .env or
.git) and the same walk as the RAG index (.gitignore respected, dependency and
cache folders skipped).
"""

from __future__ import annotations

from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.execution.file_permissions import FilePermissions, PermissionDenied
from sensai.knowledge.rag import SKIPPED_DIRS, _git_files, _walk_files

MAX_ENTRIES = 200  # beyond this, the model is asked to list a sub-folder


class ListFilesTool:
    name = "list_files"
    description = (
        "List the files of the project, or of one of its folders, one path per line "
        "(relative to the project root). Use it to find which files exist before "
        "reading them. Ignored files (.gitignore), dependencies and secrets are not "
        f"listed; at most {MAX_ENTRIES} paths are returned."
    )
    risk = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "Folder to list, relative to the project (default: all)."},
        },
        "additionalProperties": False,
    }

    def __init__(self, permissions: FilePermissions | None = None) -> None:
        self.permissions = permissions or FilePermissions.for_workspace()

    def run(self, **kwargs: Any) -> ToolResult:
        folder = kwargs.get("path") or "."
        try:
            base = self.permissions.check_read(folder)
        except PermissionDenied as exc:
            return ToolResult(ok=False, content=str(exc), data={"error": "permission_denied"})
        if not base.is_dir():
            kind = "is a file, not a folder" if base.is_file() else "does not exist"
            return ToolResult(ok=False, content=f"{folder}: {kind}", data={"error": "not_found"})

        root = self.permissions.root
        relatives = _git_files(root)
        if relatives is None:
            relatives = _walk_files(root)
        found = []
        for rel in sorted(relatives):
            if any(part in SKIPPED_DIRS for part in rel.split("/")[:-1]):
                continue
            path = root / rel
            if not path.is_relative_to(base) or not path.is_file():
                continue
            try:
                self.permissions.check_read(rel)
            except PermissionDenied:
                continue  # protected name (.env, keys…): not even its name is shown
            found.append(rel)

        if not found:
            return ToolResult(ok=True, content=f"No files in {folder}.",
                              data={"count": 0, "returned": 0})
        shown = found[:MAX_ENTRIES]
        content = "\n".join(shown)
        if len(found) > MAX_ENTRIES:
            content += (f"\n[... {len(found) - MAX_ENTRIES} more files; "
                        "call list_files with a sub-folder ...]")
        return ToolResult(ok=True, content=content,
                          data={"count": len(found), "returned": len(shown)})
