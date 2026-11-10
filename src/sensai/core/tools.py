"""
Shared contract for every tool the agent can call (feature [T1] MCP).

Every feature that exposes a capability to the agent — sandbox, RAG, external
MCP tool — implements this protocol. THIS contract is what lets the 3
workstreams work in parallel without stepping on each other: the agent only
knows the ToolRegistry, never a tool's implementation.

See docs/decisions/0002-shared-tool-registry.md for the rationale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    # JSON schema describing the expected arguments (used for function
    # calling / the bonus feature [T5] Structured Output)
    parameters: dict[str, Any]
    # Also expected by the tool gateway (ADR-0006): `risk`, one of
    # "read", "network", "write", "execute". Missing = treated as "execute",
    # so confirmation is required. See docs/architecture/tool-contract.md.

    def run(self, **kwargs) -> ToolResult:
        """Run the tool. Must NEVER raise an unhandled exception: every error
        must be encoded in ToolResult(ok=False, ...)."""
        ...


class ToolRegistry:
    """Central registry where each workstream registers its tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def describe_all(self) -> list[dict[str, Any]]:
        """Used to tell the model which tools are available."""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]

    # `name` is positional-only (the `/`): without it, a tool with a parameter
    # also called `name` would crash the call BEFORE the try below
    # ("got multiple values for argument 'name'").
    def call(self, name: str, /, **kwargs) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(ok=False, content=f"Unknown tool: {name}")
        try:
            return tool.run(**kwargs)
        except Exception as e:  # guardrail: a crashing tool must not crash the agent
            return ToolResult(ok=False, content=f"Error in tool {name}: {e}")
