"""Tests console confirmation [A3]: only an explicit "yes" authorizes."""
import pytest

from sensai.core.tools import ToolRegistry
from sensai.execution.gateway import ConfirmationRequest, ToolGateway
from sensai.execution.human_in_loop import format_request, make_console_confirmer
from sensai.execution.tool_policy import Risk, ToolPreferences
from sensai.tools.sandbox_tool import SandboxTool


def _request(summary="print(1)"):
    return ConfirmationRequest(
        tool="run_code", risk=Risk.EXECUTE, summary=summary,
        arguments={"code": "print(1)"}, timeout_s=60,
    )


def _confirmer(answer):
    shown: list[str] = []

    def ask(prompt):
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return make_console_confirmer(ask, shown.append), shown


@pytest.mark.parametrize("answer", ["o", "oui", "Y", "yes", "  OUI  "])
def test_explicit_yes_allows(answer):
    confirm, _ = _confirmer(answer)
    assert confirm(_request()) is True


@pytest.mark.parametrize("answer", ["", "n", "non", "peut-être", "ouiii", "y es"])
def test_anything_else_refuses(answer):
    confirm, _ = _confirmer(answer)
    assert confirm(_request()) is False


@pytest.mark.parametrize("error", [EOFError(), KeyboardInterrupt()])
def test_closed_input_or_interrupt_refuses(error):
    confirm, _ = _confirmer(error)
    assert confirm(_request()) is False


def test_user_sees_the_exact_plan():
    confirm, shown = _confirmer("n")
    confirm(_request("print('bonjour')"))
    text = "\n".join(shown)
    assert "print('bonjour')" in text and "run_code" in text and "execute" in text
    assert format_request(_request("print('bonjour')")) in text


class _FakeSandbox:
    """Counts executions, without Docker."""

    class config:
        @staticmethod
        def clamp_timeout(value):
            return value or 10

    def __init__(self):
        self.ran = 0

    def run(self, *a, **k):
        self.ran += 1
        raise AssertionError("must not be called without confirmation")


def test_run_code_does_not_start_without_yes_through_gateway():
    sandbox = _FakeSandbox()
    registry = ToolRegistry()
    registry.register(SandboxTool(sandbox=sandbox))
    confirm, _ = _confirmer("non")
    gateway = ToolGateway(registry, preferences=ToolPreferences(), confirm=confirm)

    result = gateway.call("run_code", code="print(1)")

    assert result.ok is False
    assert result.data["error"] == "refused"
    assert sandbox.ran == 0
