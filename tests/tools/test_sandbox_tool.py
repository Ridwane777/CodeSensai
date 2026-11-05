"""SandboxTool through the real gateway: the guarantees A3 and EV2 promise."""
from sensai.core.tools import ToolRegistry
from sensai.execution import gateway as gw
from sensai.execution.gateway import ToolGateway
from sensai.execution.guardrails import check_input, filter_output
from sensai.execution.sandbox.python_sandbox import PythonSandbox
from sensai.tools.sandbox_tool import SandboxTool
from tests.execution.sandbox.fakes import FakeClient, FakeContainer


def build(container=None, confirm=lambda req: True, **kwargs):
    client = FakeClient(container or FakeContainer(stdout=b"42\n"))
    registry = ToolRegistry()
    registry.register(SandboxTool(PythonSandbox(client=client)))
    gateway = ToolGateway(registry, confirm=confirm, **kwargs)
    return gateway, client


def test_declares_the_highest_risk():
    assert SandboxTool.risk == "execute"


def test_code_never_runs_without_explicit_confirmation():
    gateway, client = build(confirm=lambda req: False)

    result = gateway.call("run_code", code="print(42)")

    assert result.data["error"] == gw.REFUSED
    assert client.created_with == {}  # not even a container was created


def test_default_confirmer_refuses_so_nothing_runs_until_an_interface_is_plugged_in():
    registry = ToolRegistry()
    client = FakeClient()
    registry.register(SandboxTool(PythonSandbox(client=client)))

    result = ToolGateway(registry).call("run_code", code="print(1)")

    assert result.data["error"] == gw.REFUSED
    assert client.created_with == {}


def test_confirmed_run_returns_the_output():
    gateway, client = build()

    result = gateway.call("run_code", code="print(42)")

    assert result.ok is True
    assert result.content == "42\n"
    assert result.data["exit_code"] == 0
    assert client.created_with["command"][-1] == "print(42)"


def test_the_user_is_shown_the_exact_code_to_approve():
    seen = []
    gateway, _ = build(confirm=lambda req: seen.append(req) or True)

    gateway.call("run_code", code="import os\nprint(os.getcwd())", timeout_s=5)

    summary = seen[0].summary
    assert "import os\nprint(os.getcwd())" in summary
    assert "no network" in summary and "5 s" in summary


def test_failure_gives_the_model_what_it_needs_to_fix_the_code():
    stderr = (
        b"Traceback (most recent call last):\n"
        b'  File "<string>", line 1, in <module>\n'
        b"NameError: name 'x' is not defined\n"
    )
    gateway, _ = build(FakeContainer(stderr=stderr, exit_code=1))

    result = gateway.call("run_code", code="print(x)")

    assert result.ok is False
    assert "NameError" in result.content and "not defined" in result.content
    assert "Traceback" in result.content
    assert result.data["error_type"] == "NameError"


def test_timeout_is_reported_as_a_failure():
    gateway, _ = build(FakeContainer(hang=True))
    result = gateway.call("run_code", code="while True: pass", timeout_s=1)

    assert result.ok is False
    assert "Timeout" in result.content


def test_unknown_arguments_are_rejected_before_anything_runs():
    gateway, client = build()
    result = gateway.call("run_code", code="print(1)", network=True)

    assert result.data["error"] == gw.INVALID_ARGUMENTS
    assert client.created_with == {}


def test_credential_in_the_code_is_masked_before_confirmation_and_execution():
    seen = []
    gateway, client = build(
        confirm=lambda req: seen.append(req) or True, input_guards=[check_input]
    )

    gateway.call("run_code", code="key = 'sk-abcdefghijklmnop1234'\nprint(1)")

    assert "sk-abcdefghijklmnop1234" not in seen[0].summary
    assert "sk-abcdefghijklmnop1234" not in client.created_with["command"][-1]


def test_secret_printed_by_the_code_does_not_reach_the_model():
    gateway, _ = build(
        FakeContainer(stdout=b"token=sk-abcdefghijklmnop1234\n"), output_filters=[filter_output]
    )

    result = gateway.call("run_code", code="print(1)")

    assert "sk-abcdefghijklmnop1234" not in result.content
    assert "sk-abcdefghijklmnop1234" not in str(result.data)


def test_hostile_output_is_cleaned_by_the_gateway():
    gateway, _ = build(FakeContainer(stdout="ok​\x1b[31m\n".encode()))
    assert gateway.call("run_code", code="print(1)").content == "ok\n"


def test_declared_timeout_is_shorter_than_the_user_ceiling():
    assert SandboxTool.timeout_s <= 120.0
