"""
[Workstream C - Ridwane] RAG over the project's code and documentation - feature [R1].

The catalog pipeline, step by step:

1. `scan_files`   - find the files to index (no secrets, no noise);
2. `chunk_file`   - split them by structure;
3. `RagIndex.update` - compute embeddings and store them in SQLite, reprocessing
   only added, modified or deleted files;
4. `RagIndex.search` - retrieve the passages closest to a question, above a
   threshold;
5. `format_context` - format them for the model, with their source.

The choices (bge-m3, SQLite + numpy, structure-aware chunking, 0.54 threshold,
exclusions) and their measurements: docs/decisions/0009-rag-over-the-codebase.md
and docs/performance/R1-rag.md.

No LLM framework (ADR-0001): embeddings go through Ollama's HTTP API,
`/api/embed`, just as chat goes through `/api/chat`.
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import itertools
import os
import re
import sqlite3
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import requests

from sensai.knowledge.memory import ensure_private_dir, restrict_file
from sensai.knowledge.retrieval import BM25, reciprocal_rank_fusion
from sensai.knowledge.state_document import STATE_FILE

RAG_FILE = "rag.db"
DEFAULT_EMBED_MODEL = "bge-m3"
# Minimum delay between two index updates during a session (see refresh_if_stale).
REFRESH_EVERY_S = 30.0
DEFAULT_MIN_SCORE = 0.54  # measured for bge-m3: R1 (ADR-0009), then R2 (ADR-0032)
DEFAULT_TOP_K = 5
CANDIDATES = 50  # passages kept by each ranking before fusion (R2)
# Documentation passages for the search `kind` filter (US-R2-2).
DOC_SUFFIXES = (".md", ".markdown", ".rst", ".txt")

MAX_FILE_BYTES = 1_000_000
MAX_CHUNK_LINES = 80
WINDOW_LINES = 40
WINDOW_OVERLAP = 10
EMBED_BATCH = 16

# Never walked: noise (dependencies, caches) that would drown the results.
SKIPPED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".idea", ".vscode",
}

# Never indexed, even if the project's .gitignore misses them: any indexed
# passage may be sent to the model, including on a remote server.
SECRET_PATTERNS = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks",
    "*.keystore", "*.kdbx", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    ".netrc", ".pgpass", ".npmrc", ".pypirc", "credentials.json",
)

# Documents converted to text at indexing time, in the sandbox (issue #64,
# ADR-0034), as LlamaIndex, AnythingLLM or PrivateGPT do. The converted text
# is chunked like Markdown; its line numbers are the ones read_file returns
# for the same file.
DOCUMENT_FORMATS = {
    ".pdf": ".pdf", ".docx": ".docx", ".pptx": ".pptx", ".xlsx": ".xlsx",
    ".xls": ".xls", ".epub": ".epub", ".msg": ".msg",
}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

# Formats we can recognize but not read (ADR-0009, decision 7): we tell the
# user what to do instead of silently ignoring them. DOCUMENT_FORMATS belong
# here when no converter is available.
UNSUPPORTED_FORMATS = {
    ".pdf": "PDF not indexed: convert it to text (pdftotext file.pdf) "
            "or install pypdf for future support",
    ".docx": "Word not indexed: export it to Markdown or text (pandoc file.docx -o x.md)",
    ".doc": "Word not indexed: export it to text",
    ".odt": "OpenDocument not indexed: export it to Markdown or text (pandoc)",
    ".xlsx": "Spreadsheet not indexed: export it to CSV",
    ".xls": "Spreadsheet not indexed: export it to CSV",
    ".ods": "Spreadsheet not indexed: export it to CSV",
    ".pptx": "Presentation not indexed: export the slide text",
    ".epub": "E-book not indexed: convert it to text (pandoc)",
}

HEADING = re.compile(r"^#{1,6}\s")
IMPORT_LINE = re.compile(r"^\s*(import\s|from\s\S+\s+import\s)")


class EmbeddingError(RuntimeError):
    """Embeddings could not be computed (Ollama missing, model missing...)."""


# --- 1. Find the files ------------------------------------------------------


@dataclass
class ScanResult:
    files: list[Path] = field(default_factory=list)
    unsupported: list[tuple[Path, str]] = field(default_factory=list)
    documents: list[Path] = field(default_factory=list)  # to convert (ADR-0034)


def _is_secret(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_PATTERNS)


def _git_files(root: Path) -> list[str] | None:
    """Files tracked or not ignored according to git: honors .gitignore exactly.

    None if the folder is not a git repository (or git is missing).
    """
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others",
             "--exclude-standard", "-z"],
            capture_output=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return [p for p in out.decode("utf-8", errors="replace").split("\0") if p]


def _gitignore_patterns(root: Path) -> list[str]:
    path = root / ".gitignore"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    # Negations (!pattern) are not handled outside a git repository: accepted limitation.
    return [p.strip() for p in lines if p.strip() and not p.startswith(("#", "!"))]


def _ignored(rel: str, is_dir: bool, patterns: list[str]) -> bool:
    name = rel.rsplit("/", 1)[-1]
    for pattern in patterns:
        if pattern.endswith("/") and not is_dir:
            continue
        pat = pattern.rstrip("/").lstrip("/")
        target = rel if "/" in pattern.rstrip("/") else name
        if fnmatch.fnmatch(target, pat):
            return True
    return False


def _walk_files(root: Path) -> list[str]:
    """Walk without git: the root .gitignore, interpreted simply."""
    patterns = _gitignore_patterns(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIPPED_DIRS and not _ignored(prefix + d, True, patterns)
        ]
        found.extend(
            prefix + f for f in filenames if not _ignored(prefix + f, False, patterns)
        )
    return found


def _is_binary(path: Path) -> bool:
    with path.open("rb") as f:
        return b"\0" in f.read(8192)


def scan_files(root: str | Path) -> ScanResult:
    """Project text files to index, plus recognized but unsupported formats."""
    root = Path(root)
    relatives = _git_files(root)
    if relatives is None:
        relatives = _walk_files(root)

    result = ScanResult()
    for rel in sorted(relatives):
        parts = rel.split("/")
        if any(p in SKIPPED_DIRS for p in parts[:-1]) or _is_secret(parts[-1]):
            continue
        if rel == STATE_FILE:
            # Already given in full to the agent (M4, ADR-0029): not twice.
            continue
        path = root / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in DOCUMENT_FORMATS:
            try:
                too_big = path.stat().st_size > MAX_DOCUMENT_BYTES
            except OSError:
                continue
            if too_big:
                result.unsupported.append(
                    (path, f"document larger than {MAX_DOCUMENT_BYTES // 2**20} MB not indexed"))
            else:
                result.documents.append(path)
            continue
        advice = UNSUPPORTED_FORMATS.get(path.suffix.lower())
        if advice:
            result.unsupported.append((path, advice))
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES or _is_binary(path):
                continue
        except OSError:
            continue
        result.files.append(path)
    return result


# --- 2. Chunk ----------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    source: str
    start: int  # first line, numbered from 1
    end: int    # last line, inclusive
    text: str


def _windows(source: str, lines: list[str], start: int, end: int) -> Iterator[Chunk]:
    pos = start
    while pos <= end:
        stop = min(pos + WINDOW_LINES - 1, end)
        text = "\n".join(lines[pos - 1:stop])
        if text.strip():
            yield Chunk(source, pos, stop, text)
        if stop >= end:
            break
        pos = stop - WINDOW_OVERLAP + 1


def _span(source: str, lines: list[str], start: int, end: int) -> Iterator[Chunk]:
    """Passages covering lines start..end (1-indexed), with blank edge lines trimmed.

    A block longer than MAX_CHUNK_LINES is split again into overlapping windows,
    so that no passage dilutes its topic in too much text.
    """
    while start <= end and not lines[start - 1].strip():
        start += 1
    while end >= start and not lines[end - 1].strip():
        end -= 1
    if start > end:
        return
    if end - start + 1 <= MAX_CHUNK_LINES:
        yield Chunk(source, start, end, "\n".join(lines[start - 1:end]))
        return
    yield from _windows(source, lines, start, end)


def _gap(source: str, lines: list[str], start: int, end: int) -> list[Chunk]:
    """Module-level code between two definitions (docstring, constants...).

    A block containing only imports is skipped: on its own it teaches the model
    nothing and would surface the file for any question.
    """
    meaningful = [
        line for line in lines[start - 1:end] if line.strip() and not IMPORT_LINE.match(line)
    ]
    if not meaningful:
        return []
    return list(_span(source, lines, start, end))


def _chunk_python(source: str, text: str, lines: list[str]) -> list[Chunk]:
    tree = ast.parse(text)
    chunks, covered_until = [], 0
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = min([d.lineno for d in node.decorator_list] + [node.lineno])
        end = node.end_lineno or start
        chunks.extend(_gap(source, lines, covered_until + 1, start - 1))
        chunks.extend(_span(source, lines, start, end))
        covered_until = end
    chunks.extend(_gap(source, lines, covered_until + 1, len(lines)))
    return chunks


def _chunk_markdown(source: str, lines: list[str]) -> list[Chunk]:
    starts = [i + 1 for i, line in enumerate(lines) if HEADING.match(line)]
    if not starts or starts[0] != 1:
        starts.insert(0, 1)
    bounds = [*starts, len(lines) + 1]
    chunks = []
    for start, nxt in itertools.pairwise(bounds):
        chunks.extend(_span(source, lines, start, nxt - 1))
    return chunks


def chunk_file(path: str | Path, source: str) -> list[Chunk]:
    """Split a file by its structure (ADR-0009, decision 3).

    Python: one function or class per passage (via `ast`). Markdown: one section
    per heading. Anything else, or Python that does not parse: overlapping line
    blocks. Each passage keeps its lines, so it can be cited.
    """
    path = Path(path)
    return chunk_text(source, path.read_text(encoding="utf-8", errors="replace"),
                      path.suffix.lower())


def chunk_text(source: str, text: str, suffix: str) -> list[Chunk]:
    """`chunk_file` on already-read text (a converted document arrives as ".md")."""
    lines = text.splitlines()
    if not lines:
        return []
    if suffix == ".py":
        try:
            return _chunk_python(source, text, lines)
        except SyntaxError:
            pass  # file being written: fall back to line blocks
    elif suffix in (".md", ".markdown"):
        return _chunk_markdown(source, lines)
    return list(_windows(source, lines, 1, len(lines)))


# --- 3. Compute embeddings ---------------------------------------------------


Embedder = Callable[[list[str]], list[list[float]]]


class OllamaEmbedder:
    """Embeddings via `POST /api/embed` on Ollama (raw HTTP, ADR-0001)."""

    def __init__(self, host: str, model: str = DEFAULT_EMBED_MODEL, timeout: float = 300):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def __call__(self, texts: list[str]) -> list[list[float]]:
        try:
            response = requests.post(
                f"{self.host}/api/embed",
                json={"model": self.model, "input": texts},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise EmbeddingError(f"Ollama unreachable at {self.host} ({e})") from e
        if response.status_code == 404 or "not found" in response.text.lower():
            raise EmbeddingError(
                f"embedding model {self.model} not found: ollama pull {self.model}"
            )
        if not response.ok:
            raise EmbeddingError(f"Ollama answered {response.status_code}: {response.text[:200]}")
        return response.json()["embeddings"]


def _normalized(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# --- 4. Store and retrieve ----------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_meta (
    project TEXT PRIMARY KEY,
    model   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rag_files (
    project TEXT NOT NULL,
    path    TEXT NOT NULL,
    sha256  TEXT NOT NULL,
    PRIMARY KEY (project, path)
);
CREATE TABLE IF NOT EXISTS rag_chunks (
    project    TEXT NOT NULL,
    path       TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    text       TEXT NOT NULL,
    vector     BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS rag_chunks_par_fichier ON rag_chunks (project, path);
"""


@dataclass
class UpdateReport:
    files_indexed: int = 0
    files_removed: int = 0
    chunks: int = 0  # passages in the index after the update
    unsupported: list[tuple[Path, str]] = field(default_factory=list)


class RagIndex:
    """Index of a project's passages, stored in SQLite next to the sessions (M1).

    `project` separates projects within one database; `model` is the embedding
    model name: if it changes, the project's index is cleared, since vectors
    from different models are not comparable.
    """

    def __init__(
        self,
        db_path: str | Path,
        project: str,
        embed: Embedder,
        model: str = "",
        converter: Callable[..., object] | None = None,
    ):
        self.db_path = Path(db_path)
        # converter(path, extension) -> ConversionResult (execution/sandbox/
        # document_sandbox.py); None: documents are only listed.
        self.converter = converter
        self.project = project
        self.embed = embed
        self.model = model
        self._matrix: np.ndarray | None = None
        self._rows: list[tuple[str, int, int, str]] = []
        self._bm25: BM25 | None = None
        # Reranks the top passages (R2, `retrieval.LlmReranker`); None: no reranking.
        self.reranker: Callable[[str, list[dict]], list[dict]] | None = None
        self._updated_at: float | None = None  # time.monotonic() of the last update
        ensure_private_dir(self.db_path.parent)
        is_new = not self.db_path.exists()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._check_model(conn)
        if is_new:
            restrict_file(self.db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _check_model(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT model FROM rag_meta WHERE project = ?", (self.project,)
        ).fetchone()
        if row is not None and row[0] != self.model:
            conn.execute("DELETE FROM rag_chunks WHERE project = ?", (self.project,))
            conn.execute("DELETE FROM rag_files WHERE project = ?", (self.project,))
        conn.execute(
            "INSERT INTO rag_meta (project, model) VALUES (?, ?) "
            "ON CONFLICT(project) DO UPDATE SET model = excluded.model",
            (self.project, self.model),
        )

    def is_empty(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM rag_chunks WHERE project = ? LIMIT 1", (self.project,)
            ).fetchone()
        return row is None

    def refresh_if_stale(
        self, root: str | Path, every_s: float = REFRESH_EVERY_S
    ) -> UpdateReport | None:
        """Update the index if the last update is older than `every_s` seconds;
        otherwise do nothing and return None.

        Without this, a file created or modified after the first question (often
        by the agent itself) stayed invisible to search, and the model claimed it
        did not exist (trial run of 2026-11-01). An update only recomputes file
        hashes and only indexes the files that changed.
        """
        now = time.monotonic()
        if self._updated_at is not None and now - self._updated_at < every_s:
            return None
        return self.update(root)

    def update(
        self,
        root: str | Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> UpdateReport:
        """Update the index: only added, modified or deleted files.

        Each file is stored in its own transaction: if Ollama goes down midway,
        files already processed stay indexed and will not be recomputed on the
        next attempt.
        """
        root = Path(root)
        scan = scan_files(root)
        report = UpdateReport(unsupported=scan.unsupported)

        with self._connect() as conn:
            known = dict(conn.execute(
                "SELECT path, sha256 FROM rag_files WHERE project = ?", (self.project,)
            ).fetchall())

        current: dict[str, tuple[Path, str]] = {}
        for path in scan.files:
            rel = path.relative_to(root).as_posix()
            current[rel] = (path, hashlib.sha256(path.read_bytes()).hexdigest())
        documents = set()
        for path in scan.documents:
            if self.converter is None:
                report.unsupported.append((path, UNSUPPORTED_FORMATS[path.suffix.lower()]))
                continue
            rel = path.relative_to(root).as_posix()
            current[rel] = (path, hashlib.sha256(path.read_bytes()).hexdigest())
            documents.add(rel)

        to_index = [rel for rel, (_, sha) in current.items() if known.get(rel) != sha]
        removed = [rel for rel in known if rel not in current]

        with self._connect() as conn:
            for rel in removed:
                self._forget(conn, rel)
        report.files_removed = len(removed)

        indexed = 0
        for done, rel in enumerate(to_index, start=1):
            path, sha = current[rel]
            if rel in documents:
                result = self.converter(path, DOCUMENT_FORMATS[path.suffix.lower()])
                if not result.ok:
                    # No sha stored: the document is retried next time,
                    # and an old version is no longer cited.
                    report.unsupported.append((path, _document_advice(path, result)))
                    with self._connect() as conn:
                        self._forget(conn, rel)
                    if progress:
                        progress(done, len(to_index))
                    continue
                chunks = chunk_text(rel, result.text, ".md")
            else:
                chunks = chunk_file(path, rel)
            vectors = self._embed_documents(chunks)
            with self._connect() as conn:
                self._forget(conn, rel)
                conn.executemany(
                    "INSERT INTO rag_chunks (project, path, start_line, end_line, text, vector) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (self.project, rel, c.start, c.end, c.text, v.tobytes())
                        for c, v in zip(chunks, vectors, strict=True)
                    ],
                )
                conn.execute(
                    "INSERT INTO rag_files (project, path, sha256) VALUES (?, ?, ?)",
                    (self.project, rel, sha),
                )
            indexed += 1
            if progress:
                progress(done, len(to_index))
        report.files_indexed = indexed

        if to_index or removed:
            self._matrix = self._bm25 = None  # the search cache is stale
        with self._connect() as conn:
            report.chunks = conn.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE project = ?", (self.project,)
            ).fetchone()[0]
        self._updated_at = time.monotonic()
        return report

    def _forget(self, conn: sqlite3.Connection, rel: str) -> None:
        conn.execute("DELETE FROM rag_chunks WHERE project = ? AND path = ?", (self.project, rel))
        conn.execute("DELETE FROM rag_files WHERE project = ? AND path = ?", (self.project, rel))

    def _embed_documents(self, chunks: list[Chunk]) -> list[np.ndarray]:
        # The path at the top of the passage helps the model: "auth.py" already
        # says authentication. Measured this way in docs/performance/R1-rag.md.
        texts = [f"{c.source}\n{c.text}" for c in chunks]
        vectors: list[np.ndarray] = []
        for i in range(0, len(texts), EMBED_BATCH):
            vectors.extend(_normalized(self.embed(texts[i:i + EMBED_BATCH])))
        return vectors

    def _load(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT path, start_line, end_line, text, vector FROM rag_chunks "
                "WHERE project = ?", (self.project,)
            ).fetchall()
        self._rows = [(r[0], r[1], r[2], r[3]) for r in rows]
        self._bm25 = None
        self._matrix = (
            np.vstack([np.frombuffer(r[4], dtype=np.float32) for r in rows]) if rows else None
        )

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = DEFAULT_MIN_SCORE,
        kind: str | None = None,
        path: str | None = None,
        rerank: bool = True,
    ) -> list[dict]:
        """Most relevant passages for `query`, best first.

        R2 (ADR-0032): the embedding and keyword (BM25) rankings are fused (RRF),
        then `self.reranker`, if set, reranks the top ones. `kind` ("code" or
        "doc") and `path` (a folder) narrow the search (US-R2-2).

        `score` remains the embedding similarity. Below `min_score`, a passage is
        dropped, even if BM25 found it: there is always a "closest" one, even when
        the project does not contain the answer, and sending it to the model
        would encourage it to make things up (US-R1-3, US-R2-3).
        """
        if self._matrix is None:
            self._load()
        if self._matrix is None:
            return []
        q = _normalized(self.embed([query]))[0]
        if q.shape[0] != self._matrix.shape[1]:
            raise EmbeddingError(
                "the index was built with a different embedding model: it will be "
                "rebuilt on next startup"
            )
        scores = self._matrix @ q
        allowed = {
            i for i, row in enumerate(self._rows)
            if scores[i] >= min_score and _matches(row[0], kind, path)
        }
        if not allowed:
            return []
        dense = [i for i in map(int, np.argsort(-scores)) if i in allowed][:CANDIDATES]
        if self._bm25 is None:
            self._bm25 = BM25([f"{r[0]}\n{r[3]}" for r in self._rows])
        words = self._bm25.scores(query)
        lexical = sorted((i for i in allowed if words[i] > 0), key=lambda i: -words[i])
        fused = reciprocal_rank_fusion(
            [[{"i": i} for i in dense], [{"i": i} for i in lexical[:CANDIDATES]]],
            key=lambda h: h["i"],
        )
        hits = [
            {
                "source": self._rows[i][0],
                "start": self._rows[i][1],
                "end": self._rows[i][2],
                "text": self._rows[i][3],
                "score": round(float(scores[i]), 4),
            }
            for i in (h["i"] for h in fused)
        ]
        if rerank and self.reranker is not None:
            hits = self.reranker(query, hits)
        return hits[:top_k]


def _matches(source: str, kind: str | None, path: str | None) -> bool:
    """Search filters (US-R2-2): file type and folder."""
    if kind == "doc" and not source.endswith(DOC_SUFFIXES):
        return False
    if kind == "code" and source.endswith(DOC_SUFFIXES):
        return False
    folder = (path or "").strip("/")
    return not folder or source.startswith(folder + "/")


def _document_advice(path: Path, result: object) -> str:
    """Advice shown at indexing time when a document could not be converted."""
    error = getattr(result, "error", None)
    if error == "image_missing":
        return ("document not indexed: build the conversion image "
                "(docker build -t sensai-docs:latest docker/docs)")
    if error == "sandbox_error":
        return "document not indexed: Docker unavailable for conversion"
    if error == "empty" and path.suffix.lower() == ".pdf":
        return f"PDF without text (scanned?): ocrmypdf {path.name} {path.stem}-ocr.pdf"
    if error == "empty":
        return "document without text"
    return f"conversion failed ({error}): {UNSUPPORTED_FORMATS[path.suffix.lower()]}"


# --- 5. Format for the model ---------------------------------------------------


def _numbered(hit: dict) -> str:
    """Each line prefixed with its number in the file.

    A model cannot count the lines of a passage: without numbers it guesses them
    (real trial run: `cli.py:123-127` cited for code at line 112).
    """
    return "\n".join(
        f"{number}│ {line}"
        for number, line in enumerate(hit["text"].splitlines(), start=hit["start"])
    )


def format_context(hits: list[dict]) -> str:
    """Block appended to the user's question before it is sent to the model.

    The instruction explicitly allows ignoring the passages: the search runs on
    every question, even "what is a closure?", and a model given passages tends
    to comment on them instead of answering (real trial run of 2026-10-11). The
    score is not shown for the same reason.
    """
    if not hits:
        return (
            "[Automatic project search: no relevant passage.] If the question is "
            "about this project's code or documents, say you did not find the "
            "information instead of making it up. Otherwise, answer normally, "
            "without mentioning this search."
        )
    parts = [
        "[Project excerpts found automatically: they may be unrelated to the "
        "question.] If the question is about this project, rely on them and cite your "
        "sources as file:line, reading the number written at the start of each "
        "line. Otherwise, ignore them and answer normally, without mentioning these excerpts."
    ]
    for hit in hits:
        parts.append(f"--- {hit['source']}:{hit['start']}-{hit['end']}\n{_numbered(hit)}")
    return "\n\n".join(parts)


def format_search_results(query: str, hits: list[dict]) -> str:
    """Output of the `search_codebase` tool (ADR-0013).

    Unlike `format_context`, the model asked for this search itself: we do not
    tell it the passages may be off-topic or that it may ignore them (real trial
    run of 2026-10-14).
    """
    if not hits:
        return (
            f'[Search "{query}": no relevant passage in the project.] '
            "Try other words, or say you did not find the information."
        )
    parts = [
        f'[Search "{query}": {len(hits)} passage(s) from the project.] Cite your '
        "sources as file:line, reading the number written at the start of each line."
    ]
    for hit in hits:
        parts.append(f"--- {hit['source']}:{hit['start']}-{hit['end']}\n{_numbered(hit)}")
    return "\n\n".join(parts)
