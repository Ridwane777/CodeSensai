"""
[Workstream C - Ridwane] Exposes updating the state document (SENSAI.md) as
a Tool the agent can call - feature [M4], ADR-0029.

Risk `write`: every update goes through gateway confirmation (A3), which
shows `describe_call`, i.e. the section before and after.
"""
from __future__ import annotations

from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.knowledge.state_document import (
    ACTIONS,
    STATE_FILE,
    StateDocument,
    StateError,
    section_diff,
)


class UpdateStateTool:
    name = "update_state"
    risk = "write"
    # One short sentence: with a long description, qwen3-coder wrote its tool
    # calls as text (across all tools, measured on 2026-10-17).
    # How to use it is in the system prompt (state_document.py).
    description = "Updates a section of the project state document SENSAI.md."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "action": {"type": "string", "enum": list(ACTIONS)},
            "content": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["section", "action", "content"],
    }

    def __init__(self, document: StateDocument) -> None:
        self.document = document

    def describe_call(self, **args: Any) -> str:
        """What the user approves: the change to the section."""
        section = args.get("section", "")
        try:
            diff = self.document.preview(section, args.get("action", ""), args.get("content", ""))
        except StateError as e:
            return f"{STATE_FILE}, section \"{section}\" - will be rejected: {e}"
        return f"{STATE_FILE}, section \"{section}\" ({args.get('action')}):\n{diff}"

    def run(self, **kwargs: Any) -> ToolResult:
        section = str(kwargs.get("section", ""))
        try:
            old, new = self.document.update(
                section, kwargs.get("action", ""), kwargs.get("content", ""), kwargs.get("summary")
            )
        except StateError as e:
            # Tool contract: never raise, the agent must be able to fix its call.
            return ToolResult(ok=False, content=str(e), data={"error": "invalid_update"})
        except OSError as e:
            return ToolResult(ok=False, content=f"Write failed: {e.strerror}",
                              data={"error": "io"})
        return ToolResult(
            ok=True,
            content=f"{STATE_FILE} updated, section \"{section}\":\n"
            f"{section_diff(section, old, new)}",
            data={"section": section},
        )
