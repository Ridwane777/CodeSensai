"""
[Workstream C - Ridwane] Structured memory tools - feature [M3], ADR-0030.

`save_fact` (risk `write`): remember a fact, after confirmation.
`recall_facts` (risk `read`): retrieve facts, without confirmation.
The agent has no tool to delete: that is reserved for the `/facts` command.
"""
from __future__ import annotations

import sqlite3
from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.knowledge.facts import MODES, FactError, FactStore


def _fail(message: str) -> ToolResult:
    # Tool contract: never raise, the agent must be able to fix its call.
    return ToolResult(ok=False, content=message, data={"error": "invalid_fact"})


class RememberFactTool:
    name = "save_fact"
    risk = "write"
    # One short sentence and the name save_fact: with a long description or the
    # name remember_fact, qwen3-coder wrote the call as text instead of making
    # it (4/12 vs 8/12 structured calls, measured on 2026-10-17).
    # How to use it is in the system prompt (facts.py).
    description = "Saves a lasting fact about the project: entity, attribute, value."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "entity": {"type": "string"},
            "attribute": {"type": "string"},
            "value": {"type": "string"},
            "mode": {"type": "string", "enum": list(MODES)},
        },
        "required": ["entity", "attribute", "value"],
    }

    def __init__(self, store: FactStore) -> None:
        self.store = store

    def describe_call(self, **args: Any) -> str:
        try:
            return self.store.preview(args.get("entity"), args.get("attribute"),
                                      args.get("value"), args.get("mode", "replace"))
        except FactError as e:
            return f"Remember a fact - will be rejected: {e}"

    def run(self, **kwargs: Any) -> ToolResult:
        try:
            result = self.store.remember(kwargs.get("entity"), kwargs.get("attribute"),
                                         kwargs.get("value"), kwargs.get("mode", "replace"))
        except FactError as e:
            return _fail(str(e))
        except (sqlite3.Error, OSError) as e:
            return ToolResult(ok=False, content=f"Memory unavailable: {e}",
                              data={"error": "storage"})
        messages = {
            "created": "Fact saved.",
            "added": "Value added.",
            "updated": f"Fact updated (old value: {', '.join(result['old_values'])}).",
            "unchanged": "This fact was already known: nothing changed.",
        }
        content = messages[result["change"]]
        if result["others"]:
            # So the model spots a duplicate ("redis version" next to
            # "uses_redis") and reuses the right name next time.
            content += (
                f" Other known attributes of {kwargs.get('entity')}: "
                + ", ".join(f"{n} ({', '.join(v)})" for n, v in result["others"])
                + ". If one means the same thing, use its name with mode replace."
            )
        return ToolResult(ok=True, content=content, data=result)


class RecallFactsTool:
    name = "recall_facts"
    risk = "read"
    description = "Searches saved facts about the project, by entity, attribute or value."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "entity": {"type": "string"},
            "attribute": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": [],
    }

    def __init__(self, store: FactStore) -> None:
        self.store = store

    def run(self, **kwargs: Any) -> ToolResult:
        try:
            facts = self.store.recall(kwargs.get("entity"), kwargs.get("attribute"),
                                      kwargs.get("value"))
        except FactError as e:
            return _fail(str(e))
        except (sqlite3.Error, OSError) as e:
            return ToolResult(ok=False, content=f"Memory unavailable: {e}",
                              data={"error": "storage"})
        note = ""
        if not facts and kwargs.get("entity") and (kwargs.get("attribute") or kwargs.get("value")):
            # The model often guesses an attribute name other than the saved one
            # (real trial run of 2026-10-17): show it everything known about the entity.
            try:
                facts = self.store.recall(kwargs.get("entity"))
            except (FactError, sqlite3.Error, OSError):
                facts = []
            if facts:
                wanted = kwargs.get("attribute") or kwargs.get("value")
                note = (f"Nothing saved exactly for \"{wanted}\"; "
                        "here is everything known. ")
        if not facts:
            return ToolResult(ok=True, content="No fact saved for this search.",
                              data={"facts": []})
        lines = [f"- {f['entity']} - {f['attribute']}: {f['value']} (as of {f['updated_at'][:10]})"
                 for f in facts]
        return ToolResult(ok=True, content=note + "Facts found:\n" + "\n".join(lines),
                          data={"facts": facts})
