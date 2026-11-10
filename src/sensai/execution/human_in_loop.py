"""
[Workstream B — Meric] User confirmation before a risky action — feature [A3]
Human-in-the-Loop. Applies before any call to `run_code` (risk `execute`).

Cross-workstream contract (ADR-0005): HOW the question is asked belongs to the
interface. This module provides the CLI one: a `Confirmer` to pass to
`ToolGateway(confirm=...)`. The web one ("Allow" button) is
`WebConfirmationBroker`, in `web_confirmation.py` (ADR-0015): wired by
Workstream D, without touching the gateway.

Rule: only an explicit "yes" allows. Empty or unknown answer, end of stream
(closed stdin, pipe, CI) or interruption: refusal. French "o"/"oui" are also
accepted.
"""
from __future__ import annotations

from collections.abc import Callable

from .gateway import ConfirmationRequest
from .tool_policy import Risk

_YES = frozenset({"o", "oui", "y", "yes"})


def format_request(request: ConfirmationRequest) -> str:
    """The text shown to the user: the tool, its risk and the exact plan."""
    return (
        f"\n⚠ The agent wants to use \"{request.tool}\" (risk: {Risk(request.risk).value}).\n"
        f"{request.summary}\n"
        f"Answer within {request.timeout_s:g} s; no answer means refusal."
    )


def make_console_confirmer(
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> Callable[[ConfirmationRequest], bool]:
    """Build the CLI confirmer. `input_fn`/`output_fn` are for tests."""

    def confirm(request: ConfirmationRequest) -> bool:
        output_fn(format_request(request))
        try:
            answer = input_fn("Allow? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            output_fn("No answer: refused.")
            return False
        allowed = answer.strip().lower() in _YES
        output_fn("Allowed." if allowed else "Refused.")
        return allowed

    return confirm


# Ready-to-use instance : `ToolGateway(registry, confirm=cli_confirm)`.
cli_confirm = make_console_confirmer()

