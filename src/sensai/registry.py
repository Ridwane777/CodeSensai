"""
Builds the tool registry shared by every interface.

The interactive CLI (`sensai`) and the scheduler (`sensai-schedule`, feature
X5) must offer the same tools: a tool registered here reaches both, without
anyone having to remember to wire it in two places. What differs between them
is not the registry but the gateway policy (user confirmation on one side,
systematic refusal on the other).
"""
from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.tools.list_files_tool import ListFilesTool
from sensai.tools.read_file_tool import ReadFileTool
from sensai.tools.sandbox_tool import SandboxTool
from sensai.tools.web_search_tool import WebSearchTool
from sensai.tools.write_file_tool import WriteFileTool


def build_registry(permissions: FilePermissions | None = None) -> ToolRegistry:
    """Workstreams B, C and D register their tools here. One line per tool:
    this is the only place all four workstreams modify, so keep it tiny
    (see CONTRIBUTING.md).

    No tool contacts Docker when built, only on its first call: the CLI
    starts even without Docker. `permissions` comes from the `files` section
    of config.json (ADR-0011); without it, the current directory."""
    registry = ToolRegistry()
    # Workstream B: isolated execution (T2), current-directory files (T4), web (T3).
    registry.register(SandboxTool())
    registry.register(ReadFileTool(permissions))
    # See the project files without RAG (ADR-0059, trial run of 2026-11-06).
    registry.register(ListFilesTool(permissions))
    registry.register(WriteFileTool(permissions))
    registry.register(WebSearchTool())
    return registry
