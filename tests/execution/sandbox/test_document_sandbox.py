"""DocumentSandbox with a fake Docker client (issue #64, ADR-0034, level 3).

The test that matters most: `test_container_is_locked_down`. A malicious
document must only reach a throw-away container with no network, a read-only
root and the single file mounted read-only.
"""
from pathlib import Path

from sensai.execution.sandbox.document_sandbox import DocumentSandbox

from .fakes import FakeClient, FakeContainer, broken_client


def convert(tmp_path, container=None, client=None):
    document = tmp_path / "sujet.pdf"
    document.write_bytes(b"%PDF-1.7\n")
    client = client or FakeClient(container or FakeContainer(stdout=b"# Sujet\nTexte"))
    return DocumentSandbox(client=client).convert(document), client


def test_conversion_returns_the_markdown(tmp_path):
    result, client = convert(tmp_path)
    assert result.ok and result.text == "# Sujet\nTexte"
    assert client.container.removed


def test_container_is_locked_down(tmp_path):
    _, client = convert(tmp_path)
    kwargs = client.created_with
    assert kwargs["image"] == "sensai-docs:latest"
    assert kwargs["network_mode"] == "none" and kwargs["network_disabled"] is True
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    [(source, mount)] = kwargs["volumes"].items()
    assert Path(source) == tmp_path / "sujet.pdf"
    assert mount == {"bind": "/input/document.pdf", "mode": "ro"}
    assert kwargs["command"][-1] == "/input/document.pdf"


def test_missing_image_is_reported_not_pulled(tmp_path):
    result, client = convert(tmp_path, client=FakeClient(image_present=False))
    assert not result.ok and result.error == "image_missing"
    assert client.pulled == []


def test_docker_unavailable(tmp_path):
    result, _ = convert(tmp_path, client=broken_client())
    assert not result.ok and result.error == "sandbox_error"


def test_timeout_kills_the_conversion(tmp_path):
    result, client = convert(tmp_path, container=FakeContainer(hang=True))
    assert not result.ok and result.error == "timeout"
    assert client.container.killed


def test_out_of_memory(tmp_path):
    result, _ = convert(tmp_path, container=FakeContainer(oom=True, exit_code=137))
    assert not result.ok and result.error == "oom"


def test_converter_failure(tmp_path):
    result, _ = convert(tmp_path, container=FakeContainer(stderr=b"boom", exit_code=1))
    assert not result.ok and result.error == "failed"


def test_empty_text_is_reported(tmp_path):
    result, _ = convert(tmp_path, container=FakeContainer(stdout=b"  \n"))
    assert not result.ok and result.error == "empty"


def test_raw_bytes_are_not_text(tmp_path):
    # Measured: MarkItDown prints the raw file when a broken PDF cannot be parsed.
    result, _ = convert(tmp_path, container=FakeContainer(stdout=b"%PDF-1.7\n\x00binaire"))
    assert not result.ok and result.error == "failed"


def test_output_is_capped(tmp_path):
    big = b"x" * (5 * 1024 * 1024)
    result, _ = convert(tmp_path, container=FakeContainer(stdout=big))
    assert result.ok and result.truncated
    assert len(result.text.encode()) <= 2 * 1024 * 1024
