"""
End-to-end: the EV2 guardrails plugged into the real gateway. Shows the
guarantees hold together, not only each function on its own.
"""
from typing import Any, ClassVar

from sensai.core.tools import ToolRegistry, ToolResult
from sensai.execution import gateway as gw
from sensai.execution.gateway import ToolGateway
from sensai.execution.guardrails import check_input, filter_output

KEY = "sk-abcdefghijklmnop1234"


class Recorder:
    name = "recorder"
    description = "records what it receives and returns a secret"
    risk = "execute"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
    }

    def __init__(self) -> None:
        self.received: list[dict] = []

    def run(self, **kwargs) -> ToolResult:
        self.received.append(kwargs)
        return ToolResult(
            ok=True,
            content=f"ran, token={KEY}, owner jane@example.com",
            data={"log": [f"auth Bearer {'x' * 24}"]},
        )


def build(confirm):
    tool = Recorder()
    registry = ToolRegistry()
    registry.register(tool)
    gateway = ToolGateway(
        registry,
        confirm=confirm,
        input_guards=[check_input],
        output_filters=[filter_output],
    )
    return gateway, tool


def test_credential_is_masked_before_the_user_confirms_and_before_the_tool_runs():
    shown = []
    gateway, tool = build(lambda req: shown.append(req) or True)

    gateway.call("recorder", code=f"key = '{KEY}'")

    assert KEY not in shown[0].summary
    assert KEY not in str(shown[0].arguments)
    assert KEY not in tool.received[0]["code"]


def test_output_never_carries_a_secret_back_to_the_model():
    gateway, _ = build(lambda req: True)

    result = gateway.call("recorder", code="print(1)")

    assert result.ok is True
    assert KEY not in result.content
    assert "jane@example.com" not in result.content
    assert "x" * 24 not in str(result.data)


def test_secret_hidden_by_a_zero_width_character_is_still_masked():
    # Sanitizing runs before the filter, so the pattern sees the real token.
    class Sneaky(Recorder):
        def run(self, **kwargs) -> ToolResult:
            return ToolResult(ok=True, content="sk-​abcdefghijklmnop1234")

    registry = ToolRegistry()
    registry.register(Sneaky())
    gateway = ToolGateway(registry, confirm=lambda req: True, output_filters=[filter_output])

    assert gateway.call("recorder", code="x").content == "[REDACTED:api_key]"


def test_a_crashing_filter_still_withholds_the_output():
    def broken(text: str) -> str:
        raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(Recorder())
    gateway = ToolGateway(registry, confirm=lambda req: True, output_filters=[broken])

    result = gateway.call("recorder", code="x")
    assert result.data["error"] == gw.FILTER_FAILED
    assert KEY not in result.content
