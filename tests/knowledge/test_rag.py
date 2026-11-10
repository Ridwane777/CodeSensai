"""
Tests for RAG over the project — feature [R1].

Each block maps to a user story in docs/user-stories/R1-basic-rag.md;
the choices under test come from docs/decisions/0009-rag-over-the-codebase.md.

Ollama is never called: `FakeEmbedder` produces a hashed "bag of words".
Two texts that share words get close vectors, which is enough to test search
without a network or a model.

The tests that matter most:
- `test_env_never_indexed_even_without_gitignore`: an indexed secret can reach
  the model, or even a remote Ollama server. It fails if the hard-coded deny
  list is removed.
- `test_deleted_file_is_no_longer_cited`: otherwise the agent cites code that
  no longer exists.
- `test_below_threshold_nothing_is_returned`: this is what keeps the agent from
  making up an answer (US-R1-3).
"""
import hashlib
import math
import os
import re
import stat

import pytest

from sensai.knowledge.rag import (
    RagIndex,
    chunk_file,
    format_context,
    scan_files,
)

DIMS = 256


class FakeEmbedder:
    """Hashed, normalized bag of words. Counts the texts received."""

    def __init__(self):
        self.texts_received = 0

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.texts_received += len(texts)
        vectors = []
        for text in texts:
            v = [0.0] * DIMS
            for word in re.findall(r"\w+", text.lower()):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIMS] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            vectors.append([x / n for x in v])
        return vectors


FauxEmbedder = FakeEmbedder  # former name, still imported by other test modules


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text(
        '"""Authentication."""\n'
        "import hmac\n"
        "\n"
        "\n"
        "def verify_token(token, secret):\n"
        '    """Verify the login token sent by the client."""\n'
        "    return hmac.compare_digest(token, secret)\n"
        "\n"
        "\n"
        "class Session:\n"
        "    def open(self, user):\n"
        "        return user\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Project\n"
        "General overview.\n"
        "\n"
        "## Installation\n"
        "Run pip install to install the dependencies.\n"
        "\n"
        "## Deployment\n"
        "Deployment is done with docker compose on the server.\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def index(tmp_path):
    return RagIndex(tmp_path / "data" / "rag.db", project="project", embed=FakeEmbedder())


def sources(results):
    return [r["source"] for r in results]


def indexed(root):
    return [str(f.relative_to(root)) for f in scan_files(root).files]


# --- US-R1-2: index without leaks or needless waiting ------------------------


def test_env_never_indexed_even_without_gitignore(project):
    (project / ".env").write_text("DB_PASSWORD=hunter2\n", encoding="utf-8")
    (project / ".env.local").write_text("API_KEY=abc\n", encoding="utf-8")
    (project / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")
    (project / "server.pem").write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")

    files = indexed(project)

    assert ".env" not in files
    assert ".env.local" not in files
    assert "id_rsa" not in files
    assert "server.pem" not in files
    assert "src/auth.py" in files


def test_useless_folders_ignored(project):
    for folder in (".git", ".venv", "node_modules", "__pycache__"):
        (project / folder).mkdir()
        (project / folder / "noise.py").write_text("x = 1\n", encoding="utf-8")

    assert all("noise.py" not in f for f in indexed(project))


def test_gitignore_honored(project):
    (project / ".gitignore").write_text("build/\n*.log\n", encoding="utf-8")
    (project / "build").mkdir()
    (project / "build" / "generated.py").write_text("x = 1\n", encoding="utf-8")
    (project / "trace.log").write_text("error\n", encoding="utf-8")

    files = indexed(project)

    assert "build/generated.py" not in files
    assert "trace.log" not in files


def test_binaries_and_large_files_ignored(project):
    (project / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00binary")
    (project / "dump.sql").write_text("x" * 2_000_000, encoding="utf-8")

    files = indexed(project)

    assert "logo.png" not in files
    assert "dump.sql" not in files


def test_unsupported_format_listed_with_advice(project):
    """US-R1-4 / decision 7: a format we cannot read is not indexed, but we say
    what to do. (Since ADR-0034, PDF is a converted document:
    tests/knowledge/test_rag_documents.py.)"""
    (project / "notes.odt").write_bytes(b"PK\x03\x04binary")

    result = scan_files(project)

    assert all(f.name != "notes.odt" for f in result.files)
    advice = {str(p.relative_to(project)): c for p, c in result.unsupported}
    assert "notes.odt" in advice
    assert "pandoc" in advice["notes.odt"].lower()


def test_first_indexing_counts_files_and_passages(project, index):
    report = index.update(project)

    assert report.files_indexed == 2
    assert report.chunks > 0


def test_only_modified_files_are_reindexed(project, index):
    index.update(project)
    before = index.embed.texts_received

    (project / "README.md").write_text("# Project\nNew content.\n", encoding="utf-8")
    report = index.update(project)

    assert report.files_indexed == 1, "only README.md changed"
    new_texts = index.embed.texts_received - before
    assert 0 < new_texts <= 2, "auth.py must not be re-embedded"


def test_nothing_to_redo_if_nothing_changed(project, index):
    index.update(project)
    before = index.embed.texts_received

    report = index.update(project)

    assert report.files_indexed == 0
    assert index.embed.texts_received == before


def test_deleted_file_is_no_longer_cited(project, index):
    index.update(project)
    (project / "src" / "auth.py").unlink()

    report = index.update(project)

    assert report.files_removed == 1
    results = index.search("verify the login token", min_score=0.0)
    assert "src/auth.py" not in sources(results)


def test_index_survives_closing(project, tmp_path):
    db = tmp_path / "data" / "rag.db"
    RagIndex(db, project="project", embed=FakeEmbedder()).update(project)

    reopened = RagIndex(db, project="project", embed=FakeEmbedder())

    assert not reopened.is_empty()
    assert "src/auth.py" in sources(reopened.search("login token", min_score=0.0))


def test_projects_do_not_mix(project, tmp_path):
    db = tmp_path / "data" / "rag.db"
    RagIndex(db, project="project", embed=FakeEmbedder()).update(project)

    other = RagIndex(db, project="other-project", embed=FakeEmbedder())

    assert other.is_empty()
    assert other.search("login token", min_score=0.0) == []


# --- Structure-aware chunking (decision 3) -----------------------------------


def test_a_python_function_is_one_passage_with_its_lines(project):
    passages = chunk_file(project / "src" / "auth.py", "src/auth.py")

    function = next(p for p in passages if "def verify_token" in p.text)
    assert (function.start, function.end) == (5, 7)
    assert "class Session" not in function.text


def test_a_python_class_is_one_passage(project):
    passages = chunk_file(project / "src" / "auth.py", "src/auth.py")

    cls = next(p for p in passages if "class Session" in p.text)
    assert (cls.start, cls.end) == (10, 12)


def test_invalid_python_chunked_by_lines(tmp_path):
    """A file being written must not make indexing fail."""
    file = tmp_path / "broken.py"
    file.write_text("def oops(:\n    pass\n", encoding="utf-8")

    passages = chunk_file(file, "broken.py")

    assert passages and passages[0].start == 1


def test_markdown_chunked_by_section(project):
    passages = chunk_file(project / "README.md", "README.md")

    deployment = next(p for p in passages if "docker compose" in p.text)
    assert deployment.text.lstrip().startswith("## Deployment")
    assert "pip install" not in deployment.text
    assert (deployment.start, deployment.end) == (7, 8)


def test_long_text_file_chunked_into_blocks(tmp_path):
    file = tmp_path / "notes.txt"
    file.write_text("\n".join(f"line {i}" for i in range(1, 101)), encoding="utf-8")

    passages = chunk_file(file, "notes.txt")

    assert len(passages) > 1
    assert passages[0].start == 1
    assert passages[-1].end == 100


# --- US-R1-1: ask a question about my code -----------------------------------


def test_the_right_function_is_found(project, index):
    index.update(project)

    results = index.search("where do we verify the login token of the client?",
                           min_score=0.0)

    assert results[0]["source"] == "src/auth.py"
    assert results[0]["start"] == 5


def test_the_right_doc_section_is_found(project, index):
    index.update(project)

    results = index.search("how is deployment done with docker?", min_score=0.0)

    assert results[0]["source"] == "README.md"


def test_context_cites_file_and_lines(project, index):
    index.update(project)
    results = index.search("login token", min_score=0.0, top_k=1)

    context = format_context(results)

    assert "src/auth.py:5-7" in context
    assert "verify_token" in context


def test_context_numbers_each_line(project, index):
    """Real trial run: without numbers, the model cited cli.py:123-127 for code
    at line 112. A model does not count the lines of a passage: it must read
    the number in front of each one."""
    index.update(project)
    results = index.search("login token", min_score=0.0, top_k=1)

    context = format_context(results)

    assert "5│ def verify_token(token, secret):" in context
    assert "7│     return hmac.compare_digest(token, secret)" in context


def test_context_does_not_show_the_score(project, index):
    """The score does not help the model answer; when shown, the model commented
    on it ("the relevance is 0.51") instead of answering."""
    index.update(project)

    context = format_context(index.search("login token", min_score=0.0))

    assert "relevance" not in context.lower()
    assert "score" not in context.lower()


def test_context_allows_a_normal_answer_outside_the_project(project, index):
    """US-R1-1: "what is a closure?" must be answered as before, without
    comments on passages unrelated to it."""
    index.update(project)

    for context in (format_context(index.search("token", min_score=0.0)), format_context([])):
        assert "answer normally" in context
        assert "without mentioning" in context


def test_top_k_limits_the_number_of_passages(project, index):
    index.update(project)

    assert len(index.search("project", min_score=0.0, top_k=2)) <= 2


# --- US-R1-3: say when the project does not contain the answer --------------


def test_below_threshold_nothing_is_returned(project, index):
    index.update(project)

    assert index.search("broker kafka zookeeper", min_score=0.5) == []


def test_empty_context_warns_the_model():
    assert "no relevant passage" in format_context([]).lower()


def test_empty_index(index):
    assert index.is_empty()
    assert index.search("anything at all", min_score=0.0) == []


# --- Data protection (ADR-0007, reused by R1) --------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_index_created_private(tmp_path):
    folder = tmp_path / ".sensai"
    RagIndex(folder / "rag.db", project="p", embed=FakeEmbedder())

    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "rag.db").stat().st_mode) == 0o600


def test_the_state_document_is_not_indexed(tmp_path):
    """SENSAI.md is already given in full to the agent (ADR-0029): indexing it
    would send it to the model twice."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "SENSAI.md").write_text("## Done\n\n- x\n", encoding="utf-8")
    (root / "README.md").write_text("# Project\n", encoding="utf-8")

    assert indexed(root) == ["README.md"]


def test_a_file_created_after_opening_enters_the_search(tmp_path):
    """Trial run of 2026-11-01: a file created after the first question stayed
    invisible, and the model claimed it did not exist."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.md").write_text("Run the tests with pytest.\n", encoding="utf-8")
    index = RagIndex(tmp_path / "rag.db", str(project), FakeEmbedder(), model="fake")
    index.update(project)
    (project / "deployment.txt").write_text("Deployment region: eu-west-3\n", encoding="utf-8")

    assert index.refresh_if_stale(project) is None  # under 30 s: nothing is redone
    index._updated_at -= 31
    report = index.refresh_if_stale(project)
    assert report is not None and report.files_indexed == 1
    hits = index.search("deployment region", top_k=3, min_score=0.0)
    assert any(h["source"] == "deployment.txt" for h in hits)
