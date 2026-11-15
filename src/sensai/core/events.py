"""
What the agent emits during a turn - the contract between the core and the
interfaces (ADR-0005).

The idea: an agent turn does not produce "text", it produces a sequence of
EVENTS. The model thinks, calls a tool, gets a result, then answers. Each of
these steps is a distinct event.

Why this rather than a text stream: the CLI renders these events in a
terminal, the web interface sends them to the browser as JSON. Both consume
the SAME source. If the core returned pre-formatted text, the web app would
have to split it again - i.e. rebuild logic that belongs to the core, exactly
what ADR-0005 forbids.

Practical consequence: adding an event type here forces a decision on what
each interface does with it. That is intended - it is what keeps the two
interfaces from drifting apart unnoticed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Token:
    """A chunk of the final answer, to display as it streams."""
    text: str


@dataclass
class Thought:
    """The agent's reasoning before acting - the transparency requirement.

    Separate from Token so interfaces can present it differently: dimmed in
    the terminal, collapsible in the browser. Never mixed up with the answer
    to the user.
    """
    text: str


@dataclass
class ToolCall:
    """The agent asks for a tool to be run."""
    id: str  # links the call to its ToolReturn: two tools may run in a row
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolReturn:
    """The result of a ToolCall, as the registry returned it."""
    id: str
    name: str
    ok: bool
    content: str


@dataclass
class Error:
    """A failure that interrupts the turn (Ollama unreachable, etc.).

    A failing tool is NOT an Error: it is a ToolReturn(ok=False), and the
    agent carries on. Error means "this turn is lost".
    """
    message: str


@dataclass
class Done:
    """End of turn. Always the last event, including after an Error.

    Interfaces use it to know when to hand control back: show the prompt
    again in the CLI, close the stream on the web side.
    """
    reason: str = "final_answer"  # or "error", or "max_iterations"


Event = Token | Thought | ToolCall | ToolReturn | Error | Done

# Name sent over the wire for each type. Explicit rather than derived from the
# class name: renaming a class must not break the web interface.
_WIRE_NAMES = {
    Token: "token",
    Thought: "thought",
    ToolCall: "tool_call",
    ToolReturn: "tool_return",
    Error: "error",
    Done: "done",
}


def to_wire(event: Event) -> dict[str, Any]:
    """Serialize an event for the web interface (JSON).

    The CLI does not need it: it reads the objects directly.
    """
    name = _WIRE_NAMES.get(type(event))
    if name is None:
        raise TypeError(f"Unknown event type: {type(event).__name__}")
    return {"type": name, **vars(event)}
