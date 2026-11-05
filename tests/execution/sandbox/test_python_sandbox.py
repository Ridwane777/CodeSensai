"""PythonSandbox logic with a fake Docker client: no daemon needed."""
from sensai.execution.sandbox.config import SandboxConfig
from sensai.execution.sandbox.python_sandbox import PythonSandbox

from .fakes import FakeClient, FakeContainer, broken_client


def run(container: FakeContainer, code="print(1)", **kwargs):
    client = FakeClient(container)
    sandbox = PythonSandbox(client=client)
    return sandbox.run(code, **kwargs), client, container


def test_successful_run_returns_stdout():
    result, _, container = run(FakeContainer(stdout=b"hello\n"))

    assert result.ok is True
    assert result.stdout == "hello\n"
    assert result.exit_code == 0
    assert container.started and container.removed


def test_failing_program_reports_error_for_self_correction():
    stderr = (
        b"Traceback (most recent call last):\n"
        b'  File "<string>", line 1, in <module>\n'
        b"NameError: name 'x' is not defined\n"
    )
    result, _, _ = run(FakeContainer(stderr=stderr, exit_code=1))

    assert result.ok is False
    assert result.error_type == "NameError"
    assert "not defined" in result.error_message
    assert result.traceback.startswith("Traceback")


def test_timeout_kills_the_container_and_says_so():
    result, _, container = run(FakeContainer(hang=True), timeout_s=2)

    assert result.timed_out is True
    assert result.error_type == "Timeout"
    assert container.killed and container.removed
    assert container.wait_timeout == 2.0


def test_out_of_memory_is_reported():
    result, _, _ = run(FakeContainer(exit_code=137, oom=True))

    assert result.ok is False
    assert result.oom_killed is True
    assert result.error_type == "OOMKilled"


def test_unknown_non_zero_exit_gets_a_message():
    result, _, _ = run(FakeContainer(exit_code=3))
    assert result.error_message == "process exited with code 3"


def test_container_is_hardened():
    _, client, _ = run(FakeContainer())
    kwargs = client.created_with

    assert kwargs["network_mode"] == "none" and kwargs["network_disabled"] is True
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges"]
    assert kwargs["user"] == "65534:65534"
    assert kwargs["mem_limit"] == kwargs["memswap_limit"]
    assert "volumes" not in kwargs and "binds" not in kwargs
    assert kwargs["command"][:3] == ["python", "-I", "-c"]


def test_code_is_passed_as_an_argument_not_through_a_shell():
    _, client, _ = run(FakeContainer(), code="print('$(rm -rf /)')")
    assert client.created_with["command"][-1] == "print('$(rm -rf /)')"


def test_oversized_code_never_starts_a_container():
    config = SandboxConfig(max_code_bytes=10)
    client = FakeClient()
    result = PythonSandbox(config=config, client=client).run("x" * 11)

    assert result.error_type == "SandboxError"
    assert client.created_with == {}


def test_non_string_code_is_rejected():
    result = PythonSandbox(client=FakeClient()).run(["print(1)"])  # type: ignore[arg-type]
    assert result.error_type == "SandboxError"


def test_output_is_truncated_and_flagged():
    config = SandboxConfig(max_output_bytes=8)
    client = FakeClient(FakeContainer(stdout=b"0123456789"))
    result = PythonSandbox(config=config, client=client).run("print(1)")

    assert result.stdout == "01234567"
    assert result.truncated is True


def test_docker_failure_is_a_result_not_an_exception():
    result = PythonSandbox(client=broken_client()).run("print(1)")

    assert result.ok is False
    assert result.error_type == "SandboxError"
    assert "daemon went away" in result.error_message


def test_missing_image_is_pulled_once():
    client = FakeClient(image_present=False)
    PythonSandbox(client=client).run("print(1)")
    assert client.pulled == ["python:3.12-slim"]


def test_container_is_removed_even_when_reading_logs_fails():
    class BadLogs(FakeContainer):
        def logs(self, stdout=True, stderr=True):
            raise OSError("socket closed")

    container = BadLogs()
    result = PythonSandbox(client=FakeClient(container)).run("print(1)")

    assert result.error_type == "SandboxError"
    assert container.removed is True
