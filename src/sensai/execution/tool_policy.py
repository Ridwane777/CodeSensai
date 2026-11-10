"""
Risk levels, permission modes and user preferences for tools.

Part of the tool gateway contract (docs/architecture/tool-contract.md,
ADR-0006). This module decides nothing on its own: it answers a single
question — "for this tool, what must the gateway do before running it:
let it through, ask, or refuse?".
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Risk(str, Enum):
    """What a tool can damage. Every tool declares one (`risk` attribute)."""

    READ = "read"  # reads, changes nothing (RAG, reading an allowed file)
    NETWORK = "network"  # goes out to the Internet (web search)
    WRITE = "write"  # modifies the disk or durable state
    EXECUTE = "execute"  # runs code (sandbox): the worst case


class Mode(str, Enum):
    ALLOW = "allow"  # runs without asking
    ASK = "ask"  # asks for explicit confirmation (A3)
    DENY = "deny"  # never runs


_STRICTNESS = {Mode.ALLOW: 0, Mode.ASK: 1, Mode.DENY: 2}

# Requirement A3 is "the sandbox never starts without explicit confirmation":
# writing and executing therefore ask by default.
DEFAULT_MODES: dict[Risk, Mode] = {
    Risk.READ: Mode.ALLOW,
    Risk.NETWORK: Mode.ALLOW,
    Risk.WRITE: Mode.ASK,
    Risk.EXECUTE: Mode.ASK,
}

# Only these levels can be loosened by preferences. For WRITE and EXECUTE a
# preference can only tighten: otherwise a plain config file (or a prompt
# injection that managed to modify it) would disable the confirmation A3
# promises.
LOOSENABLE = frozenset({Risk.READ, Risk.NETWORK})

_KNOWN_KEYS = {
    "disabled",
    "modes",
    "max_output_chars",
    "confirm_timeout_s",
    "tool_timeout_s",
    "delegation_timeout_s",
    "confirm_after_untrusted",
}


def risk_of(tool: Any) -> Risk:
    """Risk declared by the tool. Missing or invalid => EXECUTE (fail closed).

    A tool that forgets to declare its risk must be treated as the most
    dangerous, not as harmless.
    """
    try:
        return Risk(getattr(tool, "risk", None))
    except (ValueError, TypeError):
        return Risk.EXECUTE


@dataclass(frozen=True)
class ToolPreferences:
    """User preferences on tool usage."""

    disabled: frozenset[str] = frozenset()
    modes: Mapping[str, Mode] = field(default_factory=dict)
    # Cap on what goes back to the model: a verbose tool must not flood the
    # context (see [M2] Token Budgeting).
    max_output_chars: int = 20_000
    # Time given to the interface to get the answer. Passed in the
    # confirmation request; exceeded => refusal (web HITL requirement).
    confirm_timeout_s: float = 60.0
    # Maximum duration of a tool call. A tool can declare a shorter
    # `timeout_s`, never a longer one: the user has the last word.
    tool_timeout_s: float = 120.0
    # Time given to a sub-agent (delegate_task, team_task, ADR-0037/0038);
    # same default as DELEGATION_TIMEOUT_S. On CPU, a single model call
    # exceeds it (trial run of 2026-11-06): raise it together with
    # tool_timeout_s, which stays the cap for every tool call.
    delegation_timeout_s: float = 120.0
    # Once untrusted content (a web page, a document) has been read, any tool
    # that is not read-only asks for confirmation, even if its mode is "allow".
    # Limits what an injected instruction can do without the user noticing.
    confirm_after_untrusted: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ToolPreferences:
        """Build from a dict (e.g. the "tools" key of config.json).

        Raises ValueError on any unknown key or value: a typo in "modes" must
        not be silently ignored, it would suggest a restriction is active when
        it is not.
        """
        unknown = set(data) - _KNOWN_KEYS
        if unknown:
            raise ValueError(f"Unknown tool preferences: {sorted(unknown)}")

        disabled = data.get("disabled", [])
        if not isinstance(disabled, (list, tuple, set, frozenset)) or not all(
            isinstance(n, str) for n in disabled
        ):
            raise ValueError("'disabled' must be a list of tool names")

        raw_modes = data.get("modes", {})
        if not isinstance(raw_modes, Mapping):
            raise ValueError("'modes' must map a tool name to a mode")
        modes = {}
        for tool_name, raw in raw_modes.items():
            try:
                modes[str(tool_name)] = Mode(raw)
            except ValueError:
                allowed = [m.value for m in Mode]
                raise ValueError(
                    f"Invalid mode for {tool_name!r}: {raw!r} (expected: {allowed})"
                ) from None

        max_chars = data.get("max_output_chars", cls.max_output_chars)
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
            raise ValueError("'max_output_chars' must be an integer > 0")

        timeout = data.get("confirm_timeout_s", cls.confirm_timeout_s)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("'confirm_timeout_s' must be a number > 0")

        tool_timeout = data.get("tool_timeout_s", cls.tool_timeout_s)
        if (
            isinstance(tool_timeout, bool)
            or not isinstance(tool_timeout, (int, float))
            or tool_timeout <= 0
        ):
            raise ValueError("'tool_timeout_s' must be a number > 0")

        delegation_timeout = data.get("delegation_timeout_s", cls.delegation_timeout_s)
        if (
            isinstance(delegation_timeout, bool)
            or not isinstance(delegation_timeout, (int, float))
            or delegation_timeout <= 0
        ):
            raise ValueError("'delegation_timeout_s' must be a number > 0")

        after_untrusted = data.get("confirm_after_untrusted", cls.confirm_after_untrusted)
        if not isinstance(after_untrusted, bool):
            raise ValueError("'confirm_after_untrusted' must be true or false")

        return cls(
            disabled=frozenset(disabled),
            modes=modes,
            max_output_chars=max_chars,
            confirm_timeout_s=float(timeout),
            tool_timeout_s=float(tool_timeout),
            delegation_timeout_s=float(delegation_timeout),
            confirm_after_untrusted=after_untrusted,
        )

    @classmethod
    def load(cls, path: str | Path) -> ToolPreferences:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def effective_mode(name: str, risk: Risk, prefs: ToolPreferences) -> Mode:
    """Mode applied to tool `name`: the risk default, adjusted by preferences.

    Preferences can always tighten; they can only loosen the LOOSENABLE
    levels.
    """
    default = DEFAULT_MODES[risk]
    wanted = prefs.modes.get(name)
    if wanted is None:
        return default
    if risk in LOOSENABLE or _STRICTNESS[wanted] >= _STRICTNESS[default]:
        return wanted
    return default
