"""read_file on files that are not plain text (issue #64, ADR-0034).

The converter is faked: the real one runs MarkItDown in a container
(tests/execution/sandbox/test_document_sandbox.py).

The test that matters most: `test_failed_conversion_never_returns_content`.
Whatever happens, the model gets either the real text or an honest message.
"""
import zipfile

import pytest

from sensai.execution.file_permissions import FilePermissions
from sensai.execution.sandbox.document_sandbox import ConversionResult
from sensai.tools.read_file_tool import ReadFileTool


class FakeConverter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, path, extension=None):
        self.calls.append(path)
        return self.result


@pytest.fixture
def perms(tmp_path):
    return FilePermissions.for_workspace(tmp_path)


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "requirements.pdf"
    path.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + bytes(range(256)))
    return path


def test_a_pdf_is_converted_and_read(perms, pdf):
    converter = FakeConverter(ConversionResult(ok=True, text="# Requirements\nDeux user stories."))
    result = ReadFileTool(perms, converter=converter).run(path="requirements.pdf")
    assert result.ok
    assert "Deux user stories." in result.content
    assert "converted from PDF" in result.content
    assert result.data["format"] == "pdf"


def test_converted_text_is_paged_like_a_text_file(perms, pdf):
    text = "\n".join(f"ligne {i}" for i in range(1, 11))
    converter = FakeConverter(ConversionResult(ok=True, text=text))
    tool = ReadFileTool(perms, converter=converter)
    result = tool.run(path="requirements.pdf", offset=4, limit=2)
    assert "ligne 4\nligne 5" in result.content
    assert "offset=6" in result.content


def test_a_conversion_is_reused_while_the_file_is_unchanged(perms, pdf):
    converter = FakeConverter(ConversionResult(ok=True, text="a\nb\nc"))
    tool = ReadFileTool(perms, converter=converter)
    tool.run(path="requirements.pdf", limit=1)
    tool.run(path="requirements.pdf", offset=2, limit=1)
    assert len(converter.calls) == 1


@pytest.mark.parametrize("error, expected", [
    ("image_missing", "docker build -t sensai-docs"),
    ("sandbox_error", "pdftotext"),
    ("empty", "ocrmypdf"),
    ("timeout", "pdftotext"),
])
def test_failed_conversion_never_returns_content(perms, pdf, error, expected):
    converter = FakeConverter(ConversionResult(ok=False, error=error, message="x"))
    result = ReadFileTool(perms, converter=converter).run(path="requirements.pdf")
    assert not result.ok
    assert expected in result.content
    assert "requirements.pdf" in result.content


def test_an_unknown_binary_is_named(perms, tmp_path):
    (tmp_path / "plan.dwg").write_bytes(b"AC1032" + bytes(200))
    converter = FakeConverter(ConversionResult(ok=True, text="never"))
    result = ReadFileTool(perms, converter=converter).run(path="plan.dwg")
    assert not result.ok and "AutoCAD" in result.content
    assert converter.calls == [], "only known document formats go to the sandbox"


def test_plain_text_never_goes_to_the_sandbox(perms, tmp_path):
    (tmp_path / "a.txt").write_text("un\ndeux\n")
    converter = FakeConverter(ConversionResult(ok=True, text="never"))
    result = ReadFileTool(perms, converter=converter).run(path="a.txt")
    assert result.content == "un\ndeux" and converter.calls == []


def test_a_docx_is_converted(perms, tmp_path):
    with zipfile.ZipFile(tmp_path / "cahier.docx", "w") as z:
        z.writestr("[Content_Types].xml", "x")
        z.writestr("word/document.xml", "x")
    converter = FakeConverter(ConversionResult(ok=True, text="Exigences"))
    result = ReadFileTool(perms, converter=converter).run(path="cahier.docx")
    assert result.ok and "Exigences" in result.content and "Word" in result.content


def test_documents_have_their_own_size_limit(perms, pdf, tmp_path):
    # Larger than the text limit (1 MB by default) but under the document one.
    big = tmp_path / "gros.pdf"
    big.write_bytes(b"%PDF-1.7\n" + bytes(2 * 1024 * 1024))
    converter = FakeConverter(ConversionResult(ok=True, text="ok"))
    assert ReadFileTool(perms, converter=converter).run(path="gros.pdf").ok


def test_secrets_are_still_refused(perms, tmp_path):
    (tmp_path / ".env").write_bytes(b"%PDF-1.7\n")
    converter = FakeConverter(ConversionResult(ok=True, text="never"))
    result = ReadFileTool(perms, converter=converter).run(path=".env")
    assert not result.ok and converter.calls == []
