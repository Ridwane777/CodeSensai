"""
Agent reasoning loop — feature [A1] Reasoning Loops (ReAct).

The Thought -> Action -> Observation cycle relies on Ollama's native tool
calling (ADR-0003): the tool list goes in the request's `tools` field, and the
decision to act is read from `message.tool_calls`, already structured by
Ollama. Text written by the model is NEVER interpreted as a command: it is
displayed, not executed.

A turn emits EVENTS (core/events.py), not text: see ADR-0005 and
docs/architecture/web/api-contract.md.

The agent never runs a tool itself: it goes through Workstream B's tool
gateway (execution/gateway.py, ADR-0006), which applies permissions,
validation, guardrails and confirmation before risky actions. This module does
not import it — the interface builds it and hands it over — so that the core
does not depend on Workstream B.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any, Protocol

from ..execution.guardrails import StreamRedactor, filter_output
from ..execution.output_sanitizer import fence_untrusted
from .events import Done, Error, Event, Thought, Token, ToolCall, ToolReturn
from .ollama_client import OllamaError, stream_chat_messages
from .tools import ToolRegistry, ToolResult

# Tool call written in the text instead of the `tool_calls` field: qwen3-coder
# sometimes forgets the opening <tool_call> tag, and Ollama then does not
# recognize the call. Measured on 2026-10-17: about 3 replies in 10 on a request
# like "remember that…", with or without our prompt. If the reply is nothing
# but calls, we read them (ADR-0031); otherwise nothing runs and we ask again
# without keeping the failed reply: sending it back makes the model copy it
# (observed during the trial run).
TEXTUAL_TOOL_CALL = re.compile(r"<function=[A-Za-z_][\w.-]*>|<tool_call>")
MAX_TEXTUAL_CALL_RETRIES = 2
_STRAY_TAGS = re.compile(r"</?tool_call>")
# ADR-0031: when the reply is ONLY calls in qwen3-coder's native format,
# we read them and they follow the normal path (gateway, guardrails,
# confirmation). A call mixed with text is never read.
_CALL = re.compile(
    r"\s*(?:<tool_call>\s*)?<function=([A-Za-z_][\w.-]*)>(.*?)</function>\s*(?:</tool_call>)?\s*",
    re.S,
)
_PARAM = re.compile(r"\s*<parameter=([A-Za-z_][\w.-]*)>\n?(.*?)\n?</parameter>\s*", re.S)
MAX_ITERATIONS = 6  # anti-infinite-loop guardrail: maximum number of model calls per turn



class ToolCaller(Protocol):
    """What the agent needs to use tools: in practice the ToolGateway
    (execution/gateway.py), never the raw ToolRegistry."""

    def describe_all(self) -> list[dict[str, Any]]: ...

    def call(self, name: str, /, **kwargs: Any) -> ToolResult: ...


def ollama_tools(tools: ToolCaller) -> list[dict[str, Any]]:
    """Put tool descriptions in the format of Ollama's `tools` field.

    The {"type": "function", ...} envelope is an Ollama API detail: it stays
    here, so the Tool contract (ADR-0002) does not depend on it.
    """
    return [{"type": "function", "function": d} for d in tools.describe_all()]


def run_agent_turn(
    host: str,
    model: str,
    messages: list[dict],
    tools: ToolCaller,
    num_ctx: int | None = None,
    max_iterations: int | None = None,
) -> Iterator[Event]:
    """
    Play one agent turn and emit what happens, as it happens.

    On each iteration: call the model; if it asks for tools, run them, send
    the results back and loop; otherwise its reply is the final answer. Beyond
    `max_iterations` model calls (MAX_ITERATIONS by default), the turn stops
    with Done(reason="max_iterations").

    `messages` is not modified: the turn's internal exchanges (tool calls,
    results) stay in a copy. The caller decides what it keeps in its history.

    `tools` is the tool gateway. Confirmation before risky actions is wired
    onto it by the interface, not passed here.

    `num_ctx` (M2, ADR-0045): without it, Ollama silently truncates the
    history at its own default limit, before the budget tracked by cli.py
    has had a chance to summarize anything. `None` lets Ollama decide
    (compatibility: most callers do not pass it).
    """
    options = {"num_ctx": num_ctx} if num_ctx else None
    # Maximum model calls per turn: configurable (`max_iterations` in
    # config.json, --max-iterations), MAX_ITERATIONS by default.
    limit = max_iterations or MAX_ITERATIONS
    # The raw registry has the same methods as the gateway: without this
    # explicit refusal, wiring it by mistake would run tools without
    # permissions, guardrails or confirmation, and nothing would break.
    if isinstance(tools, ToolRegistry):
        raise TypeError(
            "run_agent_turn expects the ToolGateway (ADR-0006), not the raw ToolRegistry."
        )
    messages = list(messages)
    offered = ollama_tools(tools)
    schemas = {t["function"]["name"]: t["function"].get("parameters") or {} for t in offered}
    textual_retries = 0

    for iteration in range(limit):
        content: list[str] = []
        thinking: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        # EV2: the displayed and stored reply goes through filter_output, line
        # by line; the model keeps its own text in `messages`.
        redactor = StreamRedactor()

        try:
            for message in stream_chat_messages(host, model, messages, offered,
                                                 options=options):
                if message.get("thinking"):
                    thinking.append(message["thinking"])
                if message.get("content"):
                    # Reasoning comes before the reply: deliver it as one
                    # block as soon as the reply starts, rather than word by
                    # word — one Thought per word would be unreadable in both
                    # interfaces.
                    yield from _flush_thought(thinking)
                    content.append(message["content"])
                    # Emitted even when empty: each chunk stays a point where the turn
                    # can be interrupted (Esc, "Stop"), without waiting for end of line.
                    yield Token(text=redactor.feed(message["content"]))
                tool_calls.extend(message.get("tool_calls") or [])
        except OllamaError as e:
            yield Error(message=str(e))
            yield Done(reason="error")
            return

        yield from _flush_thought(thinking)
        rest = redactor.flush()
        if rest:
            yield Token(text=rest)

        if not tool_calls:
            reply = "".join(content)
            if not TEXTUAL_TOOL_CALL.search(reply):
                yield Done()
                return
            if "<function=" not in reply and _STRAY_TAGS.sub("", reply).strip():
                # An empty <tool_call> tag after a real reply: nothing to run.
                # Real trial run on 2026-11-01: retried three times, the turn ended in
                # failure although the reply (and the tool called before) were fine.
                yield Done()
                return
            tool_calls = _read_textual_calls(reply, schemas)
            if tool_calls:
                yield Thought(text="Tool call read from the text (not recognized by Ollama).")
                content = []
        if not tool_calls:
            if textual_retries >= MAX_TEXTUAL_CALL_RETRIES or iteration == limit - 1:
                # Still unreadable after retries: stop rather than let the model
                # claim an action that did not happen.
                yield Error(message=(
                    "The model wrote a tool call in its text instead of "
                    "calling it: it was not executed. Rephrase the request."
                ))
                yield Done(reason="error")
                return
            textual_retries += 1
            yield Thought(text="Tool call written as text, not executed: retrying.")
            continue

        # Ollama needs to see its own tool request again before the results:
        # without this message, the following `role: "tool"` replies are not
        # attached to anything.
        messages.append(
            {"role": "assistant", "content": "".join(content), "tool_calls": tool_calls}
        )

        for index, call in enumerate(tool_calls):
            function = call.get("function") or {}
            name = function.get("name", "")
            # Ollama provides an id; if it is missing, make one unique within
            # the turn — the interface needs it to link the call to its result.
            call_id = call.get("id") or f"{iteration}-{index}"
            arguments, problem = _parse_arguments(function.get("arguments"))

            yield ToolCall(id=call_id, name=name, arguments=arguments)
            if problem:
                # Goes back to the model as an observation, so it fixes its
                # call: this is not a turn error.
                result = ToolResult(ok=False, content=problem)
            else:
                result = tools.call(name, **arguments)
            yield ToolReturn(id=call_id, name=name, ok=result.ok, content=result.content)

            # The model receives the result wrapped in <tool_output trust="untrusted">
            # (EV4-OUT-14): a web page or a file read may contain instructions,
            # and the system prompt (date_block) says not to follow them.
            # The interface displays the result as is (ToolReturn above).
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "tool_call_id": call_id,
                    "content": fence_untrusted(name, result.content),
                }
            )

    yield Done(reason="max_iterations")


def _read_textual_calls(reply: str, schemas: dict[str, dict]) -> list[dict[str, Any]]:
    """Calls written in qwen3-coder's native format, if the reply is ONLY that.

    Returns [] if the reply contains anything else, if a call is malformed or
    targets a tool that was not offered: nothing runs then (ADR-0031).
    """
    calls, position = [], 0
    for match in _CALL.finditer(reply):
        if match.start() != position:
            return []
        position = match.end()
        name, body = match.group(1), match.group(2)
        if name not in schemas:
            return []
        arguments, inner = {}, 0
        for param in _PARAM.finditer(body):
            if param.start() != inner:
                return []
            inner = param.end()
            arguments[param.group(1)] = _typed(param.group(2), schemas[name], param.group(1))
        if body[inner:].strip():
            return []
        calls.append({"function": {"name": name, "arguments": arguments}})
    return calls if calls and position == len(reply) else []


def _typed(raw: str, schema: dict, key: str) -> Any:
    """Convert a value read from the text to the type the tool expects;
    when in doubt, leave it as text (the gateway will validate)."""
    kind = ((schema.get("properties") or {}).get(key) or {}).get("type")
    try:
        if kind == "integer":
            return int(raw.strip())
        if kind == "number":
            return float(raw.strip())
        if kind == "boolean" and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
    except ValueError:
        pass
    return raw


def _flush_thought(thinking: list[str]) -> Iterator[Thought]:
    """Emit the accumulated reasoning as a single Thought, then clear the buffer.

    Filtered like the reply (EV2, ADR-0058): it is displayed and stored too.
    Delivered as one block, it can be filtered whole, without waiting for line ends."""
    text = filter_output("".join(thinking).strip())
    thinking.clear()
    if text:
        yield Thought(text=text)


def _parse_arguments(raw: Any) -> tuple[dict[str, Any], str | None]:
    """Validate a tool call's arguments.

    Ollama normally returns them already deserialized, but the model writes
    them: they are not trusted. Returns (arguments, problem) — a non-null
    problem prevents execution.
    """
    if raw is None:
        return {}, None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}, "Unreadable arguments: not valid JSON."
    if not isinstance(raw, dict):
        return {}, "Invalid arguments: a JSON object was expected."
    return raw, None
