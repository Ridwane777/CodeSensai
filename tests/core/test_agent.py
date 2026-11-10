"""
Tests the ReAct loop (core/agent.py) without Ollama: a fake model replays
a sequence of pre-written responses, and we check the emitted events and
what the agent sends back to the model.

Tools go through the real ToolGateway (ADR-0006), as in production.
The confirmation tests matter most: they fail if someone lets a risky
action run without explicit consent — for example by wiring the agent
back to the raw registry.
"""
from typing import Any, ClassVar

import pytest

from sensai.core import agent
from sensai.core.agent import MAX_ITERATIONS, run_agent_turn
from sensai.core.events import Done, Error, Thought, Token, ToolCall, ToolReturn
from sensai.core.ollama_client import OllamaError
from sensai.core.tools import ToolRegistry, ToolResult
from sensai.execution.gateway import ConfirmationRequest, ToolGateway, deny_all
from sensai.tools.echo_tool import EchoTool


class FakeOllama:
    """Replaces stream_chat_messages. Each item of `script` is the list of
    `message` chunks of one model call; an OllamaError in the script is
    raised instead."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, host, model, messages, tools=None, options=None):
        # Copy: the agent keeps modifying its list after the call.
        self.calls.append({"messages": list(messages), "tools": tools})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        yield from step


def tool_call(name: str, arguments: Any, call_id: str | None = "c1") -> dict:
    call: dict[str, Any] = {"function": {"name": name, "arguments": arguments}}
    if call_id is not None:
        call["id"] = call_id
    return {"content": "", "tool_calls": [call]}


@pytest.fixture
def fake(monkeypatch):
    def install(script):
        ollama = FakeOllama(script)
        monkeypatch.setattr(agent, "stream_chat_messages", ollama)
        return ollama
    return install


class RiskyTool:
    """Tool that records whether it ran — to prove it did not."""
    name = "run_code"
    description = "Runs code."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
    }
    risk = "execute"

    def __init__(self) -> None:
        self.executed = False

    def run(self, **kwargs) -> ToolResult:
        self.executed = True
        return ToolResult(ok=True, content="executed")


def gateway_with(*tools, confirm=deny_all) -> ToolGateway:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolGateway(registry, confirm=confirm)


def run(tools):
    history = [{"role": "user", "content": "question"}]
    return list(run_agent_turn("http://x", "m", history, tools))


# --- Direct answer ---------------------------------------------------------

def test_direct_answer_streams_tokens_then_done(fake):
    fake([[{"content": "Hel"}, {"content": "lo"}]])

    events = run(gateway_with())

    # One Token per received chunk (the turn stays interruptible), the text delivered
    # per complete line once filtered (EV2, ADR-0058).
    assert events == [Token(text=""), Token(text=""), Token(text="Hello"), Done()]


def test_a_secret_written_by_the_model_is_masked_even_split_into_chunks(fake):
    """EV2: the model answer is filtered before being displayed."""
    fake([[{"content": "The key is AKIA"}, {"content": "IOSFODNN7EXAMPLE.\nRegion "},
           {"content": "eu-west-3."}]])

    text = "".join(e.text for e in run(gateway_with()) if isinstance(e, Token))

    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert "[REDACTED:aws_access_key]" in text and text.endswith("Region eu-west-3.")


def test_tools_are_sent_in_ollama_format(fake):
    ollama = fake([[{"content": "ok"}]])

    run(gateway_with(EchoTool()))

    (tool,) = ollama.calls[0]["tools"]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "echo"


# --- Full cycle Thought -> Action -> Observation -> answer -----------------

def test_one_tool_call_then_the_final_answer(fake):
    fake([
        [{"thinking": "I must "}, {"thinking": "repeat."}, tool_call("echo", {"text": "hi"})],
        [{"content": "It said hi."}],
    ])

    events = run(gateway_with(EchoTool()))

    assert events == [
        Thought(text="I must repeat."),
        ToolCall(id="c1", name="echo", arguments={"text": "hi"}),
        ToolReturn(id="c1", name="echo", ok=True, content="hi"),
        Token(text=""),
        Token(text="It said hi."),
        Done(),
    ]


def test_the_tool_result_is_sent_back_to_the_model(fake):
    """Without this the model never sees the Observation and loops blindly."""
    ollama = fake([[tool_call("echo", {"text": "hi"})], [{"content": "end"}]])

    run(gateway_with(EchoTool()))

    second = ollama.calls[1]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["function"]["name"] == "echo"
    assert second[-1] == {
        "role": "tool", "tool_name": "echo", "tool_call_id": "c1",
        # EV4-OUT-14: the result reaches the model wrapped and marked untrusted.
        "content": ('<tool_output tool="echo" trust="untrusted" suspicious="false">\n'
                    'hi\n</tool_output>'),
    }


def test_the_caller_history_is_not_modified(fake):
    fake([[tool_call("echo", {"text": "x"})], [{"content": "end"}]])
    history = [{"role": "user", "content": "question"}]

    list(run_agent_turn("http://x", "m", history, gateway_with(EchoTool())))

    assert history == [{"role": "user", "content": "question"}]


def test_an_id_is_generated_if_ollama_gives_none(fake):
    fake([[tool_call("echo", {"text": "x"}, call_id=None)], [{"content": "end"}]])

    events = run(gateway_with(EchoTool()))

    call = next(e for e in events if isinstance(e, ToolCall))
    ret = next(e for e in events if isinstance(e, ToolReturn))
    assert call.id and call.id == ret.id


# --- Guardrails ------------------------------------------------------------

def test_the_loop_stops_at_max_iterations(fake):
    ollama = fake([[tool_call("echo", {"text": "again"})]] * MAX_ITERATIONS)

    events = run(gateway_with(EchoTool()))

    assert len(ollama.calls) == MAX_ITERATIONS
    assert events[-1] == Done(reason="max_iterations")


def test_the_step_count_is_configurable(fake):
    """The maximum step count comes from the configuration (ADR-0057)."""
    ollama = fake([[tool_call("echo", {"text": "again"})]] * 3)

    history = [{"role": "user", "content": "question"}]
    events = list(run_agent_turn("http://x", "m", history, gateway_with(EchoTool()),
                                 max_iterations=3))

    assert len(ollama.calls) == 3
    assert events[-1] == Done(reason="max_iterations")


def test_unreachable_ollama_gives_error_then_done(fake):
    fake([OllamaError("unreachable")])

    events = run(gateway_with())

    assert events == [Error(message="unreachable"), Done(reason="error")]


def test_an_unknown_tool_does_not_stop_the_turn(fake):
    fake([[tool_call("does_not_exist", {})], [{"content": "never mind"}]])

    events = run(gateway_with())

    ret = next(e for e in events if isinstance(e, ToolReturn))
    assert ret.ok is False
    assert events[-1] == Done()


@pytest.mark.parametrize("arguments", ["{not json", "[1, 2]"])
def test_invalid_arguments_are_not_executed(fake, arguments):
    fake([[tool_call("echo", arguments)], [{"content": "end"}]])

    events = run(gateway_with(EchoTool()))

    ret = next(e for e in events if isinstance(e, ToolReturn))
    assert ret.ok is False


def test_arguments_as_json_text_are_accepted(fake):
    fake([[tool_call("echo", '{"text": "hi"}')], [{"content": "end"}]])

    events = run(gateway_with(EchoTool()))

    ret = next(e for e in events if isinstance(e, ToolReturn))
    assert ret.content == "hi"


# --- Tool gateway and confirmation ([A3], ADR-0006) -------------------------

def test_the_raw_registry_is_rejected():
    """Wiring the registry without the gateway would skip permissions,
    guardrails and confirmation without anything else breaking."""
    registry = ToolRegistry()
    registry.register(EchoTool())

    with pytest.raises(TypeError):
        run(registry)


def test_without_a_confirmation_ui_the_risky_action_is_refused(fake):
    """No confirmation is not a yes."""
    tool = RiskyTool()
    fake([[tool_call("run_code", {"code": "print(1)"})], [{"content": "end"}]])

    events = run(gateway_with(tool))

    assert tool.executed is False
    ret = next(e for e in events if isinstance(e, ToolReturn))
    assert ret.ok is False


def test_a_user_refusal_blocks_the_action(fake):
    tool = RiskyTool()
    fake([[tool_call("run_code", {"code": "print(1)"})], [{"content": "end"}]])

    run(gateway_with(tool, confirm=lambda request: False))

    assert tool.executed is False


def test_a_crashing_ui_counts_as_a_refusal(fake):
    def confirm_that_crashes(request):
        raise ConnectionError("client disconnected")

    tool = RiskyTool()
    fake([[tool_call("run_code", {"code": "print(1)"})], [{"content": "end"}]])

    run(gateway_with(tool, confirm=confirm_that_crashes))

    assert tool.executed is False


def test_the_user_sees_the_code_before_accepting(fake):
    questions: list[ConfirmationRequest] = []
    tool = RiskyTool()
    fake([[tool_call("run_code", {"code": "import os\nos.listdir()"})], [{"content": "end"}]])

    run(gateway_with(tool, confirm=lambda request: questions.append(request) or True))

    assert tool.executed is True
    assert questions[0].arguments["code"] == "import os\nos.listdir()"


def test_a_riskless_tool_asks_nothing(fake):
    questions = []
    fake([[tool_call("echo", {"text": "x"})], [{"content": "end"}]])

    run(gateway_with(EchoTool(), confirm=questions.append))

    assert questions == []


# --- Tool call written as text (real trial run on 2026-10-17, ADR-0031) ----------

TEXTUAL_CALL = (
    "<function=run_code>\n<parameter=code>\nprint(1)\n</parameter>\n</function>\n</tool_call>"
)


def text(content: str) -> list[dict]:
    return [{"content": content}]


class TypedTool:
    """Tool with an integer parameter, to check the conversion."""
    name = "read_file"
    description = "Reads a file."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "max_lines": {"type": "integer"}},
        "required": ["path"],
    }
    risk = "read"

    def __init__(self) -> None:
        self.received: dict | None = None

    def run(self, **kwargs: Any) -> ToolResult:
        self.received = kwargs
        return ToolResult(ok=True, content="content")


def test_a_lone_call_in_the_answer_is_parsed_and_goes_through_confirmation(fake):
    """ADR-0031: qwen3-coder's native format, when Ollama did not recognize it,
    is parsed as a call — and goes through the gateway like any other."""
    risky = RiskyTool()
    requests = []
    fake([text(TEXTUAL_CALL), text("Done.")])

    events = list(run_agent_turn(
        "h", "m", [{"role": "user", "content": "go"}],
        gateway_with(risky, confirm=lambda req: requests.append(req) or True),
    ))

    assert risky.executed
    assert len(requests) == 1, "execution always asks for confirmation"
    call = next(e for e in events if isinstance(e, ToolCall))
    assert call.name == "run_code" and call.arguments == {"code": "print(1)"}
    assert any(isinstance(e, Thought) and "read from the text" in e.text for e in events)


def test_a_confirmation_refusal_also_applies(fake):
    risky = RiskyTool()
    fake([text(TEXTUAL_CALL), text("Okay, I will not run anything.")])

    list(run_agent_turn("h", "m", [{"role": "user", "content": "go"}], gateway_with(risky)))

    assert not risky.executed


def test_values_follow_the_tool_schema(fake):
    tool = TypedTool()
    fake([
        text("<function=read_file>\n<parameter=path>\nREADME.md\n</parameter>\n"
             "<parameter=max_lines>\n20\n</parameter>\n</function>"),
        text("There you go."),
    ])

    list(run_agent_turn("h", "m", [{"role": "user", "content": "read"}], gateway_with(tool)))

    assert tool.received == {"path": "README.md", "max_lines": 20}


def test_several_lone_calls_are_all_parsed(fake):
    tool = TypedTool()
    call = "<function=read_file>\n<parameter=path>\n{}\n</parameter>\n</function>"
    fake([text("<tool_call>\n" + call.format("a.py") + "\n</tool_call>\n<tool_call>\n"
               + call.format("b.py") + "\n</tool_call>"), text("Read.")])

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "read"}],
                                 gateway_with(tool)))

    assert [e.arguments["path"] for e in events if isinstance(e, ToolCall)] == ["a.py", "b.py"]


def test_a_tool_not_offered_is_never_executed(fake):
    """Only tools offered to the model can be called, even through text."""
    ollama = fake([text("<function=rm_rf>\n<parameter=path>\n/\n</parameter>\n</function>")] * 3)

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "go"}],
                                 gateway_with(RiskyTool())))

    assert not any(isinstance(e, ToolCall) for e in events)
    assert isinstance(events[-1], Done) and events[-1].reason == "error"
    assert len(ollama.calls) == 3


def test_a_call_in_the_middle_of_text_is_not_executed(fake):
    """Text that contains a call (a copied page, an explanation) is not
    parsed: only an answer that is NOTHING BUT the call is."""
    risky = RiskyTool()
    fake([text("Here is what the page said: " + TEXTUAL_CALL)] * 3)

    list(run_agent_turn("h", "m", [{"role": "user", "content": "go"}],
                        gateway_with(risky, confirm=lambda req: True)))

    assert not risky.executed


def test_the_model_is_retried_if_it_mixes_text_and_call(fake):
    risky = RiskyTool()
    ollama = fake([
        text("I will run: " + TEXTUAL_CALL),
        [tool_call("run_code", {"code": "print(1)"})],
        text("Done."),
    ])

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "go"}],
                                 gateway_with(risky, confirm=lambda req: True)))

    assert risky.executed
    assert ollama.calls[1]["messages"] == ollama.calls[0]["messages"]
    assert isinstance(events[-1], Done) and events[-1].reason == "final_answer"


def test_a_normal_answer_about_xml_is_not_retried(fake):
    ollama = fake([text("In XML, a tag is written <tag>value</tag>.")])

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "xml ?"}],
                                 gateway_with(RiskyTool())))

    assert len(ollama.calls) == 1
    assert isinstance(events[-1], Done) and events[-1].reason == "final_answer"


def test_an_empty_tool_call_tag_after_the_answer_does_not_fail_the_turn(fake):
    """Real trial run on 2026-11-01: "The task is scheduled.<tool_call>", retried three
    times then the turn failed, although the answer was correct."""
    ollama = fake([text("The task \"resume-todo\" is scheduled.<tool_call>")])

    events = list(run_agent_turn("h", "m", [{"role": "user", "content": "schedule"}],
                                 gateway_with(RiskyTool())))

    assert len(ollama.calls) == 1  # no retry
    assert isinstance(events[-1], Done) and events[-1].reason == "final_answer"
    assert not any(isinstance(e, Error) for e in events)


def test_the_displayed_reasoning_is_filtered_too(fake):
    """Audit of 2026-11-01: the answer was filtered, the reasoning (thought) was not."""
    fake([[{"thinking": "The key AKIAIOSFODNN7EXAMPLE "}, {"thinking": "is in .env."},
           {"content": "Done."}]])

    thought = next(e for e in run(gateway_with()) if isinstance(e, Thought))

    assert "AKIAIOSFODNN7EXAMPLE" not in thought.text
    assert "[REDACTED:aws_access_key]" in thought.text
