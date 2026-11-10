"""
Demo tool — implements the Tool contract (core/tools.py).

Serves as a template for sandbox_tool.py and rag_tool.py, and lets us test the
ToolRegistry and the upcoming ReAct loop before the real tools are ready.
"""
from typing import Any, ClassVar

from sensai.core.tools import ToolResult


class EchoTool:
    name = "echo"
    description = "Returns the received text unchanged. Used to test the tool registry."
    # Required by the gateway (docs/architecture/tool-contract.md): a tool with no
    # declared risk is treated as the most dangerous and asks for confirmation.
    risk = "read"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def run(self, **kwargs) -> ToolResult:
        text = kwargs.get("text", "")
        return ToolResult(ok=True, content=text)
