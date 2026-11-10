"""
Tool gateway: the only path through which the agent runs a tool.

It wraps the ToolRegistry (core/tools.py, ADR-0002) without modifying it and
enforces the same pipeline for EVERY tool:

    known tool -> enabled -> valid arguments -> permission mode
    -> input guardrails [EV2] -> confirmation [A3] -> execution
    -> valid result -> output filters [EV2] -> size cap

A tool implements none of these steps: it declares its risk and returns a
ToolResult. See docs/architecture/tool-contract.md and ADR-0006.

Gateway decisions go back to the model as a ToolResult
(ok=False, data={"error": <code>}): a refusal is an observation the agent can
use, never an exception that crashes the loop.
"""
from __future__ import annotations

import contextvars
import json
import logging
import socket
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import requests

from sensai.core.tools import Tool, ToolRegistry, ToolResult

from .output_sanitizer import find_injection_markers, sanitize
from .tool_policy import Mode, Risk, ToolPreferences, effective_mode, risk_of
from .tool_validation import check_arguments, check_result

log = logging.getLogger(__name__)

# Error codes returned in data["error"]: stable, testable, and readable by
# the ReAct loop without parsing text.
UNKNOWN_TOOL = "unknown_tool"
DISABLED = "disabled"
INVALID_ARGUMENTS = "invalid_arguments"
DENIED_BY_POLICY = "denied_by_policy"
BLOCKED = "blocked"
REFUSED = "refused"
INVALID_RESULT = "invalid_result"
FILTER_FAILED = "filter_failed"
TIMEOUT = "timeout"
NETWORK_ERROR = "network_error"
TOOL_ERROR = "tool_error"

# Network failures: the model can reasonably retry later or switch source,
# unlike a tool bug. requests raises its own exceptions, which do not all
# derive from ConnectionError.
_NETWORK_ERRORS = (
    ConnectionError,
    TimeoutError,
    socket.gaierror,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)

_TRUNCATION_MARKER = "\n[... output truncated ...]"
_SUMMARY_LIMIT = 500


@dataclass(frozen=True)
class Decision:
    """Verdict of an input guardrail.

    `replacement`, when given on an allowed decision, replaces the arguments
    (e.g. EV2 masking an API key in the code to run).
    """

    allowed: bool
    reason: str = ""
    replacement: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConfirmationRequest:
    """What the interface must show the user before an action.

    Describes the action, says nothing about HOW to show it: console for the
    CLI, button for the web (ADR-0005, point 3).
    """

    tool: str
    risk: Risk
    summary: str
    arguments: dict[str, Any]
    timeout_s: float


InputGuard = Callable[[str, dict[str, Any]], Decision]
OutputFilter = Callable[[str], str]
Confirmer = Callable[[ConfirmationRequest], bool]


def deny_all(request: ConfirmationRequest) -> bool:
    """Default confirmer: refuses everything.

    Until an interface plugs in its own confirmer, an action that needs
    confirmation does not happen. Better an unusable tool than code run
    without anyone saying yes.
    """
    return False


def _fail(code: str, content: str) -> ToolResult:
    return ToolResult(ok=False, content=content, data={"error": code})


def _apply_to_strings(value: Any, fn: OutputFilter) -> Any:
    """Apply `fn` to every string of a JSON structure (not to keys)."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _apply_to_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_apply_to_strings(v, fn) for v in value]
    return value


class _TimedOut(Exception):
    """The timeout expired before the call finished."""


def _run_bounded(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run `fn` in a thread and wait at most `timeout_s` seconds.

    A Python thread cannot be killed: after a timeout the work may keep going
    in the background. That is why the thread is a daemon (it does not keep
    the program alive) and why a tool that changes state must also bound its
    own duration (the sandbox kills its container). An exception raised by
    `fn` is re-raised in the caller.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        # Re-raised in the caller: nothing is swallowed here.
        except BaseException as exc:
            box["error"] = exc

    # The thread gets a copy of the caller's context: without it, a ContextVar
    # (the delegation depth of delegate_task, A2) would restart from its
    # default value on every tool, and the guardrail would bound nothing.
    ctx = contextvars.copy_context()
    thread = threading.Thread(target=ctx.run, args=(target,), daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        raise _TimedOut
    if "error" in box:
        raise box["error"]
    return box["value"]


class ToolGateway:
    def __init__(
        self,
        registry: ToolRegistry,
        preferences: ToolPreferences | None = None,
        confirm: Confirmer = deny_all,
        input_guards: Sequence[InputGuard] = (),
        output_filters: Sequence[OutputFilter] = (),
    ) -> None:
        self.registry = registry
        self.preferences = preferences or ToolPreferences()
        self.confirm = confirm
        self.input_guards = list(input_guards)
        self.output_filters = list(output_filters)
        # True once a tool that reads from outside the agent has answered. Used
        # by `confirm_after_untrusted`; one gateway per conversation.
        self._untrusted_seen = False

    def reset_untrusted(self) -> None:
        """Forget that untrusted content was read (call it when a conversation starts)."""
        self._untrusted_seen = False

    # -- what the model sees ----------------------------------------------

    def describe_all(self) -> list[dict[str, Any]]:
        """Tools offered to the model: neither disabled nor denied by policy.

        Not advertising a tool that will be refused anyway keeps the model
        from picking it, failing, then insisting.
        """
        return [d for d in self.registry.describe_all() if self._offered(d["name"])]

    def _offered(self, name: str) -> bool:
        tool = self.registry.get(name)
        if tool is None or name in self.preferences.disabled:
            return False
        return self._mode(name, tool) is not Mode.DENY

    def _mode(self, name: str, tool: Tool) -> Mode:
        risk = risk_of(tool)
        mode = effective_mode(name, risk, self.preferences)
        wanted = self.preferences.modes.get(name)
        if wanted is not None and wanted is not mode:
            log.warning("preference %r=%s ignored for a %s tool", name, wanted.value, risk.value)
        return mode

    # -- the pipeline -------------------------------------------------------

    # `name` is positional-only (the `/`), as in ToolRegistry.call: otherwise a
    # tool with a parameter called `name` would make the agent raise a
    # TypeError before even entering the pipeline.
    def call(self, name: str, /, **kwargs: Any) -> ToolResult:
        """Same signature as ToolRegistry.call: the agent can switch between them."""
        started = time.monotonic()
        result, mode = self._pipeline(name, kwargs)
        # Log the name, mode and outcome — never the arguments or the output:
        # they may contain exactly what EV2 must protect.
        log.info(
            "tool=%s mode=%s ok=%s error=%s ms=%d",
            name,
            mode,
            result.ok,
            result.data.get("error", "-"),
            (time.monotonic() - started) * 1000,
        )
        return result

    def _pipeline(self, name: str, args: dict[str, Any]) -> tuple[ToolResult, str]:
        tool = self.registry.get(name)
        if tool is None:
            return _fail(UNKNOWN_TOOL, f"Unknown tool: {name}"), "-"
        if name in self.preferences.disabled:
            return _fail(DISABLED, f"Tool {name} is disabled."), "-"

        problem = check_arguments(tool.parameters, args)
        if problem:
            return _fail(INVALID_ARGUMENTS, f"Invalid arguments for {name}: {problem}"), "-"

        mode = self._mode(name, tool)
        if mode is Mode.DENY:
            return _fail(DENIED_BY_POLICY, f"Tool {name} is not allowed."), mode.value

        # After reading untrusted content, anything that can act or send data
        # out asks first: an injected instruction then needs the user's yes.
        if (
            mode is Mode.ALLOW
            and self._untrusted_seen
            and self.preferences.confirm_after_untrusted
            and risk_of(tool) is not Risk.READ
        ):
            mode = Mode.ASK

        # Guardrails run BEFORE confirmation: the user must not approve an
        # action that will be blocked, nor see unmasked arguments in the
        # request.
        args, blocked = self._run_guards(name, tool, args)
        if blocked is not None:
            return blocked, mode.value

        if mode is Mode.ASK and not self._confirmed(name, tool, args):
            return (
                _fail(
                    REFUSED,
                    f"The user refused to run {name}. "
                    "Do not retry it as is: propose an alternative or ask them.",
                ),
                mode.value,
            )

        result = self._execute(name, tool, args)
        checked = self._check_output(tool, result)
        if checked.ok and risk_of(tool) in (Risk.READ, Risk.NETWORK):
            self._untrusted_seen = True
        return checked, mode.value

    def _execute(self, name: str, tool: Tool, args: dict[str, Any]) -> Any:
        """Run the tool under a timeout and classify its failures.

        `tool.run` is called here rather than `registry.call`: the registry
        turns any exception into text without a code, while the model needs to
        tell "retry later" (network, timeout) from "your call is wrong" (tool
        bug). The result then goes through validation and filters like any
        other.
        """
        limit = self.preferences.tool_timeout_s
        declared = getattr(tool, "timeout_s", None)
        if isinstance(declared, (int, float)) and not isinstance(declared, bool) and declared > 0:
            limit = min(limit, float(declared))
        try:
            return _run_bounded(lambda: tool.run(**args), limit)
        except _TimedOut:
            log.warning("tool %s did not answer after %ss", name, limit)
            return _fail(
                TIMEOUT,
                f"Tool {name} did not answer within {limit:g} s. Its result is unknown: "
                "the action may have completed. Check before retrying.",
            )
        except _NETWORK_ERRORS as exc:
            return _fail(
                NETWORK_ERROR,
                f"Network error in tool {name}: {exc}. "
                "Retry later or use another source.",
            )
        except Exception as exc:  # guardrail: a crashing tool does not crash the agent
            log.exception("tool %s failed", name)
            return _fail(TOOL_ERROR, f"Error in tool {name}: {exc}")

    def _run_guards(
        self, name: str, tool: Tool, args: dict[str, Any]
    ) -> tuple[dict[str, Any], ToolResult | None]:
        for guard in self.input_guards:
            try:
                decision = guard(name, args)
            # A broken guardrail blocks the call: it does not let it through.
            except Exception:
                log.exception("input guardrail failed for %s", name)
                return args, _fail(BLOCKED, f"Call to {name} blocked (guardrail failed).")
            # A guardrail that does not return a Decision (None, bool...) is
            # broken: block, do not guess its intent.
            if not isinstance(decision, Decision):
                log.error("invalid input guardrail for %s: %r", name, type(decision))
                return args, _fail(BLOCKED, f"Call to {name} blocked (invalid guardrail).")
            if not decision.allowed:
                reason = decision.reason or "refused by a guardrail"
                return args, _fail(BLOCKED, f"Call to {name} blocked: {reason}")
            if decision.replacement is not None:
                # Rewritten arguments are validated again: a guardrail must not
                # be able to bypass the schema the tool declared.
                problem = check_arguments(tool.parameters, decision.replacement)
                if problem:
                    return args, _fail(
                        BLOCKED, f"Call to {name} blocked (invalid rewrite: {problem})"
                    )
                args = decision.replacement
        return args, None

    def _confirmed(self, name: str, tool: Tool, args: dict[str, Any]) -> bool:
        request = ConfirmationRequest(
            tool=name,
            risk=risk_of(tool),
            summary=self._summary(name, tool, args),
            arguments=args,
            timeout_s=self.preferences.confirm_timeout_s,
        )
        try:
            # The timeout is enforced here, not just passed on: a confirmer that
            # never gets an answer (tab closed, user gone) must not freeze the
            # agent. No answer in time = refusal.
            return _run_bounded(lambda: self.confirm(request), request.timeout_s) is True
        except _TimedOut:
            log.warning("confirmation of %s unanswered after %ss: refused", name, request.timeout_s)
            return False
        # Crashed interface = refusal.
        except Exception:
            log.exception("confirmation failed for %s: treated as a refusal", name)
            return False

    @staticmethod
    def _summary(name: str, tool: Tool, args: dict[str, Any]) -> str:
        """The plan shown to the user: the tool's `describe_call`, otherwise a default."""
        describe = getattr(tool, "describe_call", None)
        if callable(describe):
            try:
                return str(describe(**args))
            except Exception:
                log.exception("describe_call failed for %s", name)
        text = f"{name}({json.dumps(args, ensure_ascii=False, default=str)})"
        return text if len(text) <= _SUMMARY_LIMIT else text[:_SUMMARY_LIMIT] + "…"

    @staticmethod
    def _log_injection_markers(name: str, content: str, data: dict[str, Any]) -> None:
        """Log which heuristics matched, never the text itself (it may hold secrets)."""
        found = set(find_injection_markers(content))
        _apply_to_strings(data, lambda text: found.update(find_injection_markers(text)) or text)
        if found:
            log.warning("output of %s looks like an injection attempt: %s", name, sorted(found))

    def _check_output(self, tool: Tool, result: Any) -> ToolResult:
        problem = check_result(result, getattr(tool, "output_schema", None))
        if problem:
            return _fail(INVALID_RESULT, f"Result of {tool.name} rejected: {problem}")

        # Deterministic cleaning comes first and does not depend on EV2: hidden
        # characters must not reach the filters either, they could hide a
        # secret from a pattern.
        content, data = sanitize(result.content), _apply_to_strings(result.data, sanitize)
        if content != result.content or data != result.data:
            log.warning("output of %s was cleaned (hidden characters or ANSI sequences)", tool.name)
        self._log_injection_markers(tool.name, content, data)
        try:
            for fn in self.output_filters:
                content = fn(content)
                data = _apply_to_strings(data, fn)
        except Exception:
            # Never return the raw output: that is exactly what the filter was
            # meant to clean.
            log.exception("output filter failed for %s", tool.name)
            return _fail(FILTER_FAILED, f"Output of {tool.name} withheld (filter failed).")

        # The cap comes AFTER the filters: cutting first could leave a secret
        # split in two, which the filter would no longer recognize.
        limit = self.preferences.max_output_chars
        if len(content) > limit:
            content = content[:limit] + _TRUNCATION_MARKER
        if len(json.dumps(data, ensure_ascii=False)) > limit:
            data = {"truncated": True, **({"error": data["error"]} if "error" in data else {})}
        return ToolResult(ok=result.ok, content=content, data=data)
