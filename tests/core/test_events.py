"""
Tests the contract between the core and the interfaces (ADR-0005).

These tests protect what the CLI and the web UI agree on: the names sent
over the wire and the guarantee that a turn always ends with Done. Breaking
them breaks Workstream D without noticing.
"""
import pytest

from sensai.cli import describe_request, render
from sensai.core.events import Done, Error, Thought, Token, ToolCall, ToolReturn, to_wire
from sensai.execution.gateway import ConfirmationRequest
from sensai.execution.tool_policy import Risk


def test_wire_names_are_stable():
    """The web UI reads these strings. Changing them breaks its code."""
    assert to_wire(Token(text="a"))["type"] == "token"
    assert to_wire(Thought(text="a"))["type"] == "thought"
    assert to_wire(ToolCall(id="1", name="echo"))["type"] == "tool_call"
    assert to_wire(ToolReturn(id="1", name="echo", ok=True, content="a"))["type"] == "tool_return"
    assert to_wire(Error(message="a"))["type"] == "error"
    assert to_wire(Done())["type"] == "done"


def test_fields_are_sent_with_the_event():
    wire = to_wire(ToolCall(id="42", name="run_code", arguments={"code": "print(1)"}))

    assert wire == {
        "type": "tool_call",
        "id": "42",
        "name": "run_code",
        "arguments": {"code": "print(1)"},
    }


def test_a_call_and_its_result_share_the_same_id():
    """Without this id, two chained tools can no longer be matched to each
    other on the UI side."""
    call = ToolCall(id="7", name="echo", arguments={"text": "x"})
    ret = ToolReturn(id="7", name="echo", ok=True, content="x")

    assert to_wire(call)["id"] == to_wire(ret)["id"]


def test_an_object_that_is_not_an_event_is_rejected():
    """Better to fail here than send the browser JSON it cannot read."""
    with pytest.raises(TypeError):
        to_wire("just text")


def test_default_done_is_a_final_answer():
    assert Done().reason == "final_answer"


def test_the_cli_renders_every_event():
    """Terminal and web rendering start from the same events: if a type is not
    handled here, it will be missing on the web side too."""
    assert render(Token(text="hi")) == "hi"
    assert "reasoning" in render(Thought(text="reasoning"))
    assert "run_code" in render(ToolCall(id="1", name="run_code"))
    assert "✓" in render(ToolReturn(id="1", name="echo", ok=True, content="ok"))
    assert "✗" in render(ToolReturn(id="1", name="echo", ok=False, content="failed"))
    assert "Error" in render(Error(message="Ollama unreachable"))
    assert render(Done()) == ""


def test_a_stop_at_max_iterations_is_reported():
    """Otherwise a cut-off turn displays as an empty answer."""
    assert "Maximum" in render(Done(reason="max_iterations"))


def test_confirmation_shows_the_code_verbatim():
    """The gateway's JSON summary would escape newlines: the user must approve
    the code exactly as it will run."""
    request = ConfirmationRequest(
        tool="run_code",
        risk=Risk.EXECUTE,
        summary="",
        arguments={"code": "import os\nos.listdir()"},
        timeout_s=1,
    )

    assert "import os\nos.listdir()" in describe_request(request)


def test_confirmation_shows_the_tool_plan_when_it_provides_one():
    """A tool that provides `describe_call` (write_file, update_state) shows the
    change itself: that is what the user approves (US-M4-3)."""
    request = ConfirmationRequest(
        tool="update_state",
        risk=Risk.WRITE,
        summary="SENSAI.md, section \"In progress\":\n--- before\n+++ after\n-- R2\n+- M4",
        arguments={"section": "In progress", "action": "replace", "content": "- M4"},
        timeout_s=1,
    )

    text = describe_request(request)

    assert "-- R2" in text and "+- M4" in text
