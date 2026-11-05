"""
[Lot B] Exposes the Python sandbox to the agent as a tool — feature [T2].

The tool only declares itself and returns what happened. Confirmation (A3),
credential masking (EV2), output sanitizing and time limits are applied by the
tool gateway (docs/architecture/tool-contract.md), the same way as for every other tool.
"""
from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.execution.sandbox.config import SandboxConfig
from sensai.execution.sandbox.python_sandbox import PythonSandbox
from sensai.execution.sandbox.result import ExecutionResult

# Cap per stream: the model needs the error and the end of the output, not a
# megabyte of logs. The gateway enforces its own, larger cap afterwards.
_MAX_STREAM_CHARS = 6_000


def _clip(text: str, keep_end: bool = False) -> str:
    if len(text) <= _MAX_STREAM_CHARS:
        return text
    marker = "[... clipped ...]"
    return marker + text[-_MAX_STREAM_CHARS:] if keep_end else text[:_MAX_STREAM_CHARS] + marker


class SandboxTool:
    name = "run_code"
    description = (
        "Run Python code in an isolated, throw-away container and return its output. "
        "No network, no access to the user's files, 256 MB of memory, 10 s by default "
        "(60 s at most). If it fails, read error_type, error_message and the traceback, "
        "fix the code and call the tool again."
    )
    # The worst case: the model's own code runs. The gateway therefore always
    # asks the user first, and no preference can lower that.
    risk = "execute"
    # Above the sandbox maximum (60 s) to leave room for starting the container.
    # The sandbox kills its own container, which the gateway cannot do.
    timeout_s = 90.0
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source code to run."},
            "timeout_s": {
                "type": "number",
                "description": "Time limit in seconds (default 10, maximum 60).",
            },
        },
        "required": ["code"],
        "additionalProperties": False,
    }

    def __init__(self, sandbox: PythonSandbox | None = None) -> None:
        self.sandbox = sandbox or PythonSandbox()

    def describe_call(self, **args: Any) -> str:
        """What the user is asked to approve: the exact code, in full."""
        config: SandboxConfig = self.sandbox.config
        limit = config.clamp_timeout(args.get("timeout_s"))
        return (
            f"Run this Python code in an isolated container "
            f"(no network, {config.mem_limit} of memory, {limit:g} s limit):\n\n"
            f"{args.get('code', '')}"
        )

    def run(self, **kwargs: Any) -> ToolResult:
        result = self.sandbox.run(kwargs.get("code", ""), kwargs.get("timeout_s"))
        return ToolResult(ok=result.ok, content=self._format(result), data=result.to_dict())

    @staticmethod
    def _format(result: ExecutionResult) -> str:
        parts: list[str] = []
        if result.ok:
            parts.append(_clip(result.stdout) or "(no output)")
            if result.stderr.strip():
                parts.append("stderr:\n" + _clip(result.stderr, keep_end=True))
        else:
            parts.append(f"Execution failed: {result.error_type}: {result.error_message}")
            if result.traceback:
                parts.append(_clip(result.traceback, keep_end=True))
            elif result.stderr.strip():
                parts.append("stderr:\n" + _clip(result.stderr, keep_end=True))
            if result.stdout:
                parts.append("stdout before the failure:\n" + _clip(result.stdout))
        if result.truncated:
            parts.append("(output was truncated)")
        return "\n".join(parts)
