"""Structured result of a sandboxed Python execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass

TRACEBACK_MARKER = "Traceback (most recent call last):"


def extract_traceback(stderr: str) -> str | None:
    """stderr from the last traceback header onward, or None.

    The last one matters when exceptions are chained.
    """
    index = stderr.rfind(TRACEBACK_MARKER)
    if index == -1:
        return None
    return stderr[index:].rstrip("\n")


def parse_error(traceback: str | None) -> tuple[str | None, str | None]:
    """(error_type, error_message) read from the last line of a traceback."""
    if not traceback:
        return None, None
    lines = [line for line in traceback.strip().splitlines() if line.strip()]
    if not lines:
        return None, None
    last = lines[-1]
    if last.startswith((" ", "\t")):  # an indented line is not an exception line
        return None, None
    name, sep, message = last.partition(":")
    name = name.strip()
    if not name or " " in name:
        return None, None
    return name.rsplit(".", 1)[-1], message.strip() if sep else ""


@dataclass
class ExecutionResult:
    ok: bool
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    traceback: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    timed_out: bool = False
    oom_killed: bool = False
    duration_s: float = 0.0
    truncated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def failure(cls, error_type: str, message: str, duration_s: float = 0.0) -> ExecutionResult:
        """Result for a problem outside the executed program (Docker down, code too big)."""
        return cls(
            ok=False,
            exit_code=None,
            error_type=error_type,
            error_message=message,
            duration_s=duration_s,
        )
