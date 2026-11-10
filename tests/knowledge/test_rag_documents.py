"""
Document indexing (PDF, Office, EPUB) by the RAG — issue #64, ADR-0034.

Like LlamaIndex, AnythingLLM or PrivateGPT, the RAG converts documents at
indexing time. The converter is faked here; the real one runs in the sandbox
(tests/execution/sandbox/test_document_sandbox.py).

The tests that matter most:
- `test_a_question_without_naming_the_file_finds_the_document`: this is the
  goal, finding a requirement without knowing it lives in the PDF.
- `test_without_converter_nothing_breaks`: without Docker, we fall back to the
  R1 behavior (the document is listed with advice).
"""
import pytest

from sensai.execution.sandbox.document_sandbox import ConversionResult
from sensai.knowledge.rag import RagIndex, scan_files
from tests.knowledge.test_rag import FakeEmbedder

REQUIREMENTS = """# Constraints
The project must use docker-compose and listen on port 8080.

# Deliverables
At least two user stories per feature.
"""


class FakeConverter:
    def __init__(self, result=None):
        self.result = result or ConversionResult(ok=True, text=REQUIREMENTS)
        self.calls = []

    def __call__(self, path, extension=None):
        self.calls.append((path.name, extension))
        return self.result


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (root / "requirements.pdf").write_bytes(b"%PDF-1.7\n\x00binary")
    return root


def index_with(tmp_path, converter):
    return RagIndex(tmp_path / "rag.db", project="p", embed=FakeEmbedder(),
                    converter=converter)


def test_scan_recognizes_documents(project):
    result = scan_files(project)
    assert [p.name for p in result.documents] == ["requirements.pdf"]
    assert all(p.name != "requirements.pdf" for p in result.files)


def test_a_question_without_naming_the_file_finds_the_document(tmp_path, project):
    index = index_with(tmp_path, FakeConverter())
    report = index.update(project)
    assert report.files_indexed == 2 and report.unsupported == []
    passages = index.search("how many user stories per feature?", min_score=0.0)
    assert passages[0]["source"] == "requirements.pdf"
    assert "two user stories" in passages[0]["text"]


def test_converter_receives_the_extension(tmp_path, project):
    converter = FakeConverter()
    index_with(tmp_path, converter).update(project)
    assert converter.calls == [("requirements.pdf", ".pdf")]


def test_a_document_is_converted_only_once(tmp_path, project):
    converter = FakeConverter()
    index = index_with(tmp_path, converter)
    index.update(project)
    index.update(project)
    assert len(converter.calls) == 1
    (project / "requirements.pdf").write_bytes(b"%PDF-1.7\n\x00new version")
    index.update(project)
    assert len(converter.calls) == 2


def test_missing_image_is_reported_and_retried(tmp_path, project):
    converter = FakeConverter(ConversionResult(ok=False, error="image_missing"))
    index = index_with(tmp_path, converter)
    report = index.update(project)
    advice = {p.name: c for p, c in report.unsupported}
    assert "docker build -t sensai-docs" in advice["requirements.pdf"]
    assert report.files_indexed == 1
    index.update(project)
    assert len(converter.calls) == 2, "the document must be retried"


def test_a_scanned_pdf_suggests_ocr(tmp_path, project):
    converter = FakeConverter(ConversionResult(ok=False, error="empty"))
    report = index_with(tmp_path, converter).update(project)
    assert "ocrmypdf" in dict((p.name, c) for p, c in report.unsupported)["requirements.pdf"]


def test_without_converter_nothing_breaks(tmp_path, project):
    report = index_with(tmp_path, None).update(project)
    advice = {p.name: c for p, c in report.unsupported}
    assert "pdf" in advice["requirements.pdf"].lower()
    assert report.files_indexed == 1


def test_a_document_that_became_unreadable_is_removed(tmp_path, project):
    index = index_with(tmp_path, FakeConverter())
    index.update(project)
    index.converter = FakeConverter(ConversionResult(ok=False, error="failed"))
    (project / "requirements.pdf").write_bytes(b"%PDF-1.7\n\x00damaged")
    index.update(project)
    sources = {h["source"] for h in index.search("user stories", min_score=0.0)}
    assert "requirements.pdf" not in sources, "stale text must not stay cited"
