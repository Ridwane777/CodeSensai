"""
Delegating a subtask to a sub-agent - feature [A2] Multi-Agent
Orchestration (ADR-0037).

The main agent splits a complex task into subtasks and delegates each one to a
sub-agent that runs its own ReAct loop (core/agent.py), with its own history
(isolated from the current conversation) and, optionally, its own role
(persona). The sub-agent calls the SAME tools through the SAME gateway
(ADR-0006): a risky action requires confirmation whether the main agent or a
sub-agent decides it, and the EV2 guardrails apply the same way.

Choices measured with the real model:
- the sub-agent receives the project prompt (profile, SENSAI.md, facts);
  otherwise it ignores what the main agent knows and may contradict it;
- a sub-agent does not re-delegate (MAX_DELEGATION_DEPTH = 1): at depth 2, a
  lost sub-agent re-delegated three times and returned an empty answer in 120 s;
- it stops at its deadline: without that, it kept going after being abandoned
  and still asked for write confirmations nobody was waiting for.
"""
from __future__ import annotations

import contextvars
import functools
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from sensai.core.agent import ToolCaller
from sensai.core.agent import run_agent_turn as _run_agent_turn
from sensai.core.events import Done, Error, Token
from sensai.core.tools import ToolResult

MAX_DELEGATION_DEPTH = 1
# The gateway keeps the shorter of the two timeouts (its own, 120 s by default,
# and this one). The sub-agent stops well before: the deadline is only checked
# between two events, and a model call already in flight can last about twenty
# seconds (measured: a 5 s margin was not enough).
DELEGATION_TIMEOUT_S = 120.0
STOP_MARGIN_S = 30.0

_depth: contextvars.ContextVar[int] = contextvars.ContextVar("delegation_depth", default=0)

# Tools that launch other agents: never offered to a sub-agent.
DELEGATION_TOOLS = frozenset({"delegate_task", "team_task"})


# Never offered to a sub-agent, whatever its role: scheduling a task that will
# replay a prompt unattended remains a decision of the main agent, with the
# user's consent (ADR-0052).
NEVER_DELEGATED = frozenset({"schedule_task"})


@dataclass(frozen=True)
class Role:
    """A specialized agent (A2, ADR-0038): its instructions and the only tools it sees."""

    prompt: str
    tools: frozenset[str]


# list_files (ADR-0059): without RAG, the only way for a role to see the project files.
_READ = frozenset({"read_file", "list_files", "search_codebase", "recall_facts"})
ROLES: dict[str, Role] = {
    "explorateur": Role(
        "You are the team explorer. You read and search the project; you change "
        "nothing. Return a short, factual report: the files and functions involved, "
        "what they do, and the constraints the task must respect.",
        _READ | {"web_search"},
    ),
    "developpeur": Role(
        "You are the team developer. From the task and the work you received, "
        "produce the requested change. If the task requires writing a file, use "
        "write_file. End with the code you produced and a summary of what you did.",
        _READ | {"write_file", "run_code"},
    ),
    "relecteur": Role(
        "You are the team reviewer, and you change nothing. Do not trust the developer "
        "report: before judging, always read every file involved with read_file, then "
        "check the code line by line against the task, mentally trying a few examples "
        "(including edge cases). Start your answer with APPROVED only if the code you "
        "read is correct; otherwise start with NEEDS FIX, followed by the precise list "
        "of defects.",
        _READ,
    ),
}


class AgentRunner(Protocol):
    """What DelegateTool needs to run a sub-agent turn: in practice
    run_agent_turn (core/agent.py), replaced by a fake turn in tests."""

    def __call__(self, host: str, model: str, messages: list[dict], tools: ToolCaller) -> Any: ...


class _SubAgentTools:
    """The gateway as seen by a sub-agent: neither the delegation tools (it does
    not re-delegate) nor those outside its role are offered, and after the
    deadline no tool runs or asks for confirmation anymore."""

    def __init__(
        self,
        tools: ToolCaller,
        deadline: float,
        role: Role | None,
        on_call: Callable[[str, dict, ToolResult], None] | None = None,
    ) -> None:
        self.tools, self.deadline, self.role, self.on_call = tools, deadline, role, on_call

    def _allowed(self, name: str) -> bool:
        if name in NEVER_DELEGATED:
            return False
        if name in DELEGATION_TOOLS:
            return False
        return self.role is None or name in self.role.tools

    def describe_all(self) -> list[dict[str, Any]]:
        return [d for d in self.tools.describe_all() if self._allowed(d.get("name", ""))]

    def call(self, name: str, /, **kwargs: Any) -> ToolResult:
        if name in DELEGATION_TOOLS:
            return ToolResult(
                ok=False, content="A sub-agent does not re-delegate: do this subtask yourself."
            )
        if not self._allowed(name):
            return ToolResult(ok=False, content=f"Tool \"{name}\" is not allowed for this role.")
        if time.monotonic() >= self.deadline:
            return ToolResult(
                ok=False, content="Subtask deadline exceeded: tool not run."
            )
        result = self.tools.call(name, **kwargs)
        if self.on_call:
            self.on_call(name, kwargs, result)
        return result


class DelegateTool:
    name = "delegate_task"
    description = (
        "Delegates a subtask to a sub-agent, which handles it with the same tools and "
        "returns its answer. Use it when the request covers several independent files or "
        "parts (three or more): delegate one subtask per file or part, then combine the "
        "answers. Do not use it for a simple question or for one or two files: do it "
        "yourself. The sub-agent does not see the conversation: each subtask must be "
        "self-contained."
    )
    # The sub-agent may call any tool, including risky ones: what matters is the
    # risk of EACH call it makes, filtered by the same gateway. Declaring
    # "execute" here prevents a permissive policy on this tool alone from being
    # used to bypass the confirmations of the tools it uses.
    risk = "execute"
    timeout_s = DELEGATION_TIMEOUT_S
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "The subtask to perform, phrased as a self-contained instruction "
                    "(the sub-agent does not see the current conversation)."
                ),
            },
            "role": {
                "type": "string",
                "enum": sorted(ROLES),
                "description": (
                    "Specialized agent: explorateur (explorer: reads and searches, changes "
                    "nothing), developpeur (developer: can write), relecteur (reviewer: "
                    "checks, changes nothing). Optional."
                ),
            },
            "persona": {
                "type": "string",
                "description": (
                    "Role to give the sub-agent (e.g. \"security reviewer\"). Optional."
                ),
            },
        },
        "required": ["task"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        host: str,
        model: str,
        tools: ToolCaller,
        run_turn: AgentRunner | None = None,
        system_prompt: Callable[[], str] | None = None,
        num_ctx: int | None = None,
    ) -> None:
        self.host = host
        self.model = model
        self.tools = tools
        # M2, ADR-0045: without num_ctx, a sub-agent is still subject to Ollama's
        # default truncation, which the CLI avoids for the main loop. An explicit
        # `run_turn` (tests) is used as is.
        self.run_turn = run_turn or functools.partial(_run_agent_turn, num_ctx=num_ctx)
        # The project prompt (profile, SENSAI.md, facts), re-read on every
        # delegation just as the CLI re-reads it every turn.
        self.system_prompt = system_prompt

    def describe_call(self, **args: Any) -> str:
        """What the user is asked to approve: the subtask in plain text."""
        who = args.get("role") or args.get("persona")
        task = args.get("task", "")
        return f"Delegate to a sub-agent ({who}): {task}" if who else f"Delegate: {task}"

    def _system(self, role: Role | None, persona: str | None) -> str:
        parts = [self.system_prompt() if self.system_prompt else ""]
        if role:
            parts.append(role.prompt)
        if persona:
            parts.append(f"Your role for this subtask: {persona}" if any(parts) else persona)
        return "\n\n".join(p for p in parts if p)

    def run(self, **kwargs) -> ToolResult:
        return self.delegate(
            kwargs.get("task") or "", role=kwargs.get("role"), persona=kwargs.get("persona")
        )

    def delegate(
        self,
        task: str,
        *,
        role: str | None = None,
        persona: str | None = None,
        deadline: float | None = None,
        on_call: Callable[[str, dict, ToolResult], None] | None = None,
    ) -> ToolResult:
        """Runs a sub-agent until its answer or its deadline (`deadline`, in
        time.monotonic(); this tool's own by default). `on_call` sees every tool
        the sub-agent runs (the team uses it to know what the developer actually
        wrote)."""
        if not task.strip():
            return ToolResult(ok=False, content="The subtask is empty.")
        if role and role not in ROLES:
            return ToolResult(
                ok=False, content=f"Unknown role: {role} (roles: {', '.join(sorted(ROLES))})."
            )
        spec = ROLES[role] if role else None

        depth = _depth.get()
        if depth >= MAX_DELEGATION_DEPTH:
            return ToolResult(
                ok=False,
                content=(
                    f"Delegation depth exceeded ({MAX_DELEGATION_DEPTH}): a "
                    "sub-agent does not re-delegate, do this subtask yourself."
                ),
            )

        messages: list[dict] = []
        system = self._system(spec, persona)
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": task})

        if deadline is None:
            deadline = time.monotonic() + self.timeout_s - STOP_MARGIN_S
        token = _depth.set(depth + 1)
        content: list[str] = []
        errors: list[str] = []
        max_iterations = timed_out = False
        tools = _SubAgentTools(self.tools, deadline, spec, on_call)
        turn = self.run_turn(self.host, self.model, messages, tools)
        try:
            for event in turn:
                if isinstance(event, Token):
                    content.append(event.text)
                elif isinstance(event, Error):
                    errors.append(event.message)
                elif isinstance(event, Done) and event.reason == "max_iterations":
                    max_iterations = True
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
        finally:
            close = getattr(turn, "close", None)
            if close:
                close()  # really stops the sub-agent: nothing keeps running in the background
            _depth.reset(token)

        reply = "".join(content).strip()
        if errors:
            return ToolResult(ok=False, content=f"The sub-agent failed: {'; '.join(errors)}")
        if timed_out:
            partial = f" Partial answer:\n{reply}" if reply else ""
            return ToolResult(
                ok=False,
                content=(
                    "The sub-agent reached its deadline and stopped." + partial
                ),
            )
        if not reply:
            return ToolResult(ok=False, content="The sub-agent produced no answer.")
        if max_iterations:
            reply += "\n[sub-agent stopped after the maximum number of iterations]"
        return ToolResult(ok=True, content=reply)
