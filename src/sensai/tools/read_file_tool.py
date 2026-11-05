"""
[Lot B] read_file — reads a text file inside the allowed folders — feature [T4].

Paths are checked by execution.file_permissions before the file is opened.
The content is untrusted data (a file can contain instructions): the gateway
fences it and, with `confirm_after_untrusted`, asks before any later write.

Files that are not text (issue #64, ADR-0034): the type is identified from the
content; PDF, Office and EPUB files are converted to Markdown in a sandboxed
container (execution/sandbox/document_sandbox.py); anything else gets a
message that names the format and says how to read it, never a guess.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.execution.file_permissions import FilePermissions, PermissionDenied
from sensai.knowledge.documents import (
    CONVERTIBLE,
    EXTENSIONS,
    identify,
    looks_binary,
    unreadable_message,
)

DEFAULT_LIMIT = 500  # lines per call: the model pages with `offset`
# Documents are converted, not loaded as text: their own, larger limit.
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


class ReadFileTool:
    name = "read_file"
    description = (
        "Read a file from the project: text, or PDF / Office / EPUB converted to text. "
        "Returns at most `limit` lines "
        "(default 500) starting at line `offset` (1-based); if the file is longer, "
        "call again with a later offset. Paths are relative to the project root. "
        "Secrets (.env, keys, .git) and anything outside the project are refused."
    )
    risk = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the project."},
            "offset": {"type": "integer", "description": "First line to return (1-based)."},
            "limit": {"type": "integer", "description": "Maximum number of lines."},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        permissions: FilePermissions | None = None,
        converter: Callable[..., Any] | None = None,
    ) -> None:
        self.permissions = permissions or FilePermissions.for_workspace()
        # Called as converter(path, extension); DocumentSandbox by default,
        # created on first use (Docker is only needed for documents).
        self._converter = converter
        # (path, mtime, size) -> converted text: paging must not convert again.
        self._converted: dict[tuple[str, int, int], str] = {}

    def run(self, **kwargs: Any) -> ToolResult:
        offset = max(int(kwargs.get("offset") or 1), 1)
        limit = max(int(kwargs.get("limit") or DEFAULT_LIMIT), 1)
        try:
            path = self.permissions.check_read(kwargs.get("path", ""))
        except PermissionDenied as exc:
            return ToolResult(ok=False, content=str(exc), data={"error": "permission_denied"})
        if not path.is_file():
            kind = "is a folder, not a file" if path.is_dir() else "does not exist"
            return ToolResult(ok=False, content=f"{path.name}: {kind}", data={"error": "not_found"})
        header = ""
        fmt = "text"
        try:
            stat = path.stat()
            size = stat.st_size
            kind = identify(path)
            if kind.kind in CONVERTIBLE:
                if size > MAX_DOCUMENT_BYTES:
                    return ToolResult(
                        ok=False,
                        content=f"File is {size} bytes, over the {MAX_DOCUMENT_BYTES} "
                        "limit for documents.",
                        data={"error": "too_large", "format": kind.kind},
                    )
                key = (str(path), stat.st_mtime_ns, size)
                text = self._converted.get(key)
                if text is None:
                    if self._converter is None:
                        from sensai.execution.sandbox.document_sandbox import DocumentSandbox

                        self._converter = DocumentSandbox()
                    result = self._converter(path, EXTENSIONS[kind.kind])
                    if not result.ok:
                        return ToolResult(
                            ok=False,
                            content=unreadable_message(path, kind, reason=result.error),
                            data={"error": result.error, "format": kind.kind},
                        )
                    text = self._converted[key] = result.text
                header = (f"[{path.name}: converted from {kind.label} to Markdown by "
                          "MarkItDown; layout may be approximate]\n")
                fmt = kind.kind
            else:
                max_bytes = self.permissions.max_read_bytes
                if size > max_bytes:
                    return ToolResult(
                        ok=False,
                        content=f"File is {size} bytes, over the {max_bytes} limit.",
                        data={"error": "too_large"},
                    )
                try:
                    if looks_binary(path):
                        raise UnicodeDecodeError("utf-8", b"", 0, 1, "NUL byte")
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    return ToolResult(
                        ok=False,
                        content=unreadable_message(path, kind),
                        data={"error": "not_text", "format": kind.kind},
                    )
        except OSError as exc:
            return ToolResult(
                ok=False, content=f"Cannot read: {exc.strerror}", data={"error": "io"}
            )

        lines = text.splitlines()
        chunk = lines[offset - 1 : offset - 1 + limit]
        content = "\n".join(chunk)
        end = offset - 1 + len(chunk)
        if end < len(lines):
            content += (
                f"\n[... lines {offset}-{end} of {len(lines)}; continue with offset={end + 1} ...]"
            )
        elif not chunk and lines:
            content = f"[offset {offset} is past the end: the file has {len(lines)} lines]"
        return ToolResult(
            ok=True,
            content=header + content,
            data={"path": str(path), "lines": len(lines), "returned": len(chunk),
                  "format": fmt},
        )
