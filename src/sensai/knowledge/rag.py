"""
[Lot C — Ridwane] RAG sur le code et la documentation du projet — feature [R1].

Le pipeline du catalogue, étape par étape :

1. `scan_files`   — repérer les fichiers à indexer (sans secrets ni bruit) ;
2. `chunk_file`   — les découper selon leur structure ;
3. `RagIndex.update` — calculer les embeddings et les ranger dans SQLite, en ne
   retraitant que les fichiers ajoutés, modifiés ou supprimés ;
4. `RagIndex.search` — retrouver les passages les plus proches d'une question,
   au-dessus d'un seuil ;
5. `format_context` — les mettre en forme pour le modèle, avec leur source.

Les choix (bge-m3, SQLite + numpy, découpage par structure, seuil 0,50,
exclusions) et leurs mesures : docs/decisions/0009-rag-sur-la-codebase.md et
docs/performance/R1-rag.md.

Pas de framework LLM (ADR-0001) : les embeddings passent par l'API HTTP
d'Ollama, `/api/embed`, comme le chat passe par `/api/chat`.
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
# Délai minimal entre deux mises à jour de l'index pendant une session (voir refresh_if_stale).
REFRESH_EVERY_S = 30.0
DEFAULT_MIN_SCORE = 0.54  # mesuré pour bge-m3 : R1 (ADR-0009), puis R2 (ADR-0032)
DEFAULT_TOP_K = 5
CANDIDATES = 50  # passages gardés par chaque classement avant la fusion (R2)
# Passages de documentation pour le filtre `kind` de la recherche (US-R2-2).
DOC_SUFFIXES = (".md", ".markdown", ".rst", ".txt")

MAX_FILE_BYTES = 1_000_000
MAX_CHUNK_LINES = 80
WINDOW_LINES = 40
WINDOW_OVERLAP = 10
EMBED_BATCH = 16

# Jamais parcourus : du bruit (dépendances, caches) qui noierait les résultats.
SKIPPED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".idea", ".vscode",
}

# Jamais indexés, même si le .gitignore du projet les oublie : tout passage
# indexé peut être envoyé au modèle, y compris sur un serveur distant.
SECRET_PATTERNS = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks",
    "*.keystore", "*.kdbx", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    ".netrc", ".pgpass", ".npmrc", ".pypirc", "credentials.json",
)

# Documents convertis en texte à l'indexation, dans la sandbox (issue #64,
# ADR-0034), comme le font LlamaIndex, AnythingLLM ou PrivateGPT. Le texte
# converti est découpé comme du Markdown ; ses numéros de ligne sont ceux que
# read_file renvoie pour le même fichier.
DOCUMENT_FORMATS = {
    ".pdf": ".pdf", ".docx": ".docx", ".pptx": ".pptx", ".xlsx": ".xlsx",
    ".xls": ".xls", ".epub": ".epub", ".msg": ".msg",
}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

# Formats que l'on sait reconnaître mais pas lire (ADR-0009, décision 7) : on
# dit à l'utilisateur quoi faire plutôt que de les ignorer en silence. Les
# DOCUMENT_FORMATS en font partie quand aucun convertisseur n'est disponible.
UNSUPPORTED_FORMATS = {
    ".pdf": "PDF non indexé : le convertir en texte (pdftotext fichier.pdf) "
            "ou installer pypdf pour une future prise en charge",
    ".docx": "Word non indexé : l'exporter en Markdown ou en texte (pandoc fichier.docx -o x.md)",
    ".doc": "Word non indexé : l'exporter en texte",
    ".odt": "OpenDocument non indexé : l'exporter en Markdown ou en texte (pandoc)",
    ".xlsx": "Tableur non indexé : l'exporter en CSV",
    ".xls": "Tableur non indexé : l'exporter en CSV",
    ".ods": "Tableur non indexé : l'exporter en CSV",
    ".pptx": "Présentation non indexée : exporter le texte des diapositives",
    ".epub": "Livre numérique non indexé : le convertir en texte (pandoc)",
}

HEADING = re.compile(r"^#{1,6}\s")
IMPORT_LINE = re.compile(r"^\s*(import\s|from\s\S+\s+import\s)")


class EmbeddingError(RuntimeError):
    """Les embeddings n'ont pas pu être calculés (Ollama absent, modèle manquant...)."""


# --- 1. Repérer les fichiers ------------------------------------------------


@dataclass
class ScanResult:
    files: list[Path] = field(default_factory=list)
    unsupported: list[tuple[Path, str]] = field(default_factory=list)
    documents: list[Path] = field(default_factory=list)  # à convertir (ADR-0034)


def _is_secret(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_PATTERNS)


def _git_files(root: Path) -> list[str] | None:
    """Fichiers suivis ou non ignorés selon git : respecte exactement le .gitignore.

    None si le dossier n'est pas un dépôt git (ou si git est absent).
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
    # Les négations (!motif) ne sont pas gérées hors d'un dépôt git : limite assumée.
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
    """Parcours sans git : .gitignore de la racine interprété simplement."""
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
    """Fichiers texte du projet à indexer, et formats reconnus mais non pris en charge."""
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
            # Déjà donné en entier à l'agent (M4, ADR-0029) : pas deux fois.
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
                    (path, f"document de plus de {MAX_DOCUMENT_BYTES // 2**20} Mo non indexé"))
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


# --- 2. Découper -------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    source: str
    start: int  # première ligne, numérotée à partir de 1
    end: int    # dernière ligne, incluse
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
    """Passages couvrant les lignes start..end (1-indexées), lignes vides des bords retirées.

    Un bloc plus long que MAX_CHUNK_LINES est redécoupé en fenêtres qui se
    chevauchent, pour qu'aucun passage ne dilue sa question dans trop de texte.
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
    """Code de niveau module entre deux définitions (docstring, constantes...).

    Un bloc qui ne contient que des imports est ignoré : seul, il n'apprend rien
    au modèle et ferait remonter le fichier pour n'importe quelle question.
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
    """Découpe un fichier selon sa structure (ADR-0009, décision 3).

    Python : une fonction ou une classe par passage (via `ast`). Markdown : une
    section par titre. Le reste, ou un Python qui ne se parse pas : des blocs de
    lignes qui se chevauchent. Chaque passage garde ses lignes, pour être cité.
    """
    path = Path(path)
    return chunk_text(source, path.read_text(encoding="utf-8", errors="replace"),
                      path.suffix.lower())


def chunk_text(source: str, text: str, suffix: str) -> list[Chunk]:
    """`chunk_file` sur un texte déjà lu (un document converti arrive en ".md")."""
    lines = text.splitlines()
    if not lines:
        return []
    if suffix == ".py":
        try:
            return _chunk_python(source, text, lines)
        except SyntaxError:
            pass  # fichier en cours d'écriture : on retombe sur les blocs de lignes
    elif suffix in (".md", ".markdown"):
        return _chunk_markdown(source, lines)
    return list(_windows(source, lines, 1, len(lines)))


# --- 3. Calculer les embeddings ---------------------------------------------


Embedder = Callable[[list[str]], list[list[float]]]


class OllamaEmbedder:
    """Embeddings via `POST /api/embed` d'Ollama (HTTP brut, ADR-0001)."""

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
            raise EmbeddingError(f"Ollama injoignable sur {self.host} ({e})") from e
        if response.status_code == 404 or "not found" in response.text.lower():
            raise EmbeddingError(
                f"modèle d'embeddings {self.model} introuvable : ollama pull {self.model}"
            )
        if not response.ok:
            raise EmbeddingError(f"Ollama a répondu {response.status_code} : {response.text[:200]}")
        return response.json()["embeddings"]


def _normalized(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# --- 4. Ranger et retrouver --------------------------------------------------

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
    chunks: int = 0  # passages dans l'index après la mise à jour
    unsupported: list[tuple[Path, str]] = field(default_factory=list)


class RagIndex:
    """Index des passages d'un projet, stocké dans SQLite à côté des sessions (M1).

    `project` sépare les projets dans une même base ; `model` est le nom du
    modèle d'embeddings : si on en change, l'index du projet est vidé, car des
    vecteurs de modèles différents ne se comparent pas.
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
        # document_sandbox.py) ; None : les documents sont seulement listés.
        self.converter = converter
        self.project = project
        self.embed = embed
        self.model = model
        self._matrix: np.ndarray | None = None
        self._rows: list[tuple[str, int, int, str]] = []
        self._bm25: BM25 | None = None
        # Reclasse les premiers passages (R2, `retrieval.LlmReranker`) ; None : pas de reclassement.
        self.reranker: Callable[[str, list[dict]], list[dict]] | None = None
        self._updated_at: float | None = None  # time.monotonic() de la dernière mise à jour
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
        """Remet l'index à jour si la dernière mise à jour date de plus de `every_s`
        secondes ; sinon ne fait rien et renvoie None.

        Sans ça, un fichier créé ou modifié après la première question (par
        l'agent lui-même, souvent) restait invisible à la recherche, et le modèle
        affirmait qu'il n'existait pas (essai du 2026-11-01). Une mise à jour ne
        recalcule que l'empreinte des fichiers et n'indexe que ceux qui ont changé.
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
        """Met l'index à jour : seuls les fichiers ajoutés, modifiés ou supprimés.

        Chaque fichier est enregistré dans sa propre transaction : si Ollama
        tombe au milieu, les fichiers déjà traités restent indexés et ne seront
        pas recalculés à la prochaine tentative.
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
                    # Pas de sha enregistré : le document est réessayé la fois
                    # suivante, et une ancienne version n'est plus citée.
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
            self._matrix = self._bm25 = None  # le cache de recherche n'est plus à jour
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
        # Le chemin en tête du passage aide le modèle : « auth.py » parle déjà
        # d'authentification. Mesuré ainsi dans docs/performance/R1-rag.md.
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
        """Passages les plus pertinents pour `query`, du meilleur au moins bon.

        R2 (ADR-0032) : les classements par embeddings et par mots (BM25) sont
        fusionnés (RRF), puis `self.reranker`, s'il existe, reclasse les premiers.
        `kind` (« code » ou « doc ») et `path` (un dossier) restreignent la
        recherche (US-R2-2).

        `score` reste la similarité des embeddings. Sous `min_score`, un passage
        est écarté, même trouvé par BM25 : il y a toujours un « plus proche »,
        même quand le projet ne contient pas la réponse, et l'envoyer au modèle
        l'inciterait à inventer (US-R1-3, US-R2-3).
        """
        if self._matrix is None:
            self._load()
        if self._matrix is None:
            return []
        q = _normalized(self.embed([query]))[0]
        if q.shape[0] != self._matrix.shape[1]:
            raise EmbeddingError(
                "l'index a été construit avec un autre modèle d'embeddings : il sera "
                "reconstruit au prochain démarrage"
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
    """Filtres de la recherche (US-R2-2) : type de fichier et dossier."""
    if kind == "doc" and not source.endswith(DOC_SUFFIXES):
        return False
    if kind == "code" and source.endswith(DOC_SUFFIXES):
        return False
    folder = (path or "").strip("/")
    return not folder or source.startswith(folder + "/")


def _document_advice(path: Path, result: object) -> str:
    """Conseil affiché à l'indexation quand un document n'a pas pu être converti."""
    error = getattr(result, "error", None)
    if error == "image_missing":
        return ("document non indexé : construire l'image de conversion "
                "(docker build -t sensai-docs:latest docker/docs)")
    if error == "sandbox_error":
        return "document non indexé : Docker indisponible pour la conversion"
    if error == "empty" and path.suffix.lower() == ".pdf":
        return f"PDF sans texte (scanné ?) : ocrmypdf {path.name} {path.stem}-ocr.pdf"
    if error == "empty":
        return "document sans texte"
    return f"conversion impossible ({error}) : {UNSUPPORTED_FORMATS[path.suffix.lower()]}"


# --- 5. Mettre en forme pour le modèle ---------------------------------------


def _numbered(hit: dict) -> str:
    """Chaque ligne précédée de son numéro dans le fichier.

    Un modèle ne sait pas compter les lignes d'un passage : sans numéros, il les
    devine (essai réel : `cli.py:123-127` cité pour du code situé ligne 112).
    """
    return "\n".join(
        f"{number}│ {line}"
        for number, line in enumerate(hit["text"].splitlines(), start=hit["start"])
    )


def format_context(hits: list[dict]) -> str:
    """Bloc ajouté à la question de l'utilisateur avant l'envoi au modèle.

    La consigne autorise explicitement à ignorer les passages : la recherche
    tourne à chaque question, même « c'est quoi une closure ? », et un modèle à
    qui l'on fournit des passages a tendance à les commenter au lieu de répondre
    (essai réel du 2026-10-11). Le score n'est pas montré pour la même raison.
    """
    if not hits:
        return (
            "[Recherche automatique dans le projet : aucun passage pertinent.] Si la "
            "question porte sur le code ou les documents de ce projet, dis que tu n'as "
            "pas trouvé l'information au lieu de l'inventer. Sinon, réponds normalement, "
            "sans mentionner cette recherche."
        )
    parts = [
        "[Extraits du projet trouvés automatiquement : ils peuvent ne pas concerner la "
        "question.] Si la question porte sur ce projet, appuie-toi sur eux et cite tes "
        "sources sous la forme fichier:ligne, en lisant le numéro écrit en début de "
        "ligne. Sinon, ignore-les et réponds normalement, sans mentionner ces extraits."
    ]
    for hit in hits:
        parts.append(f"--- {hit['source']}:{hit['start']}-{hit['end']}\n{_numbered(hit)}")
    return "\n\n".join(parts)


def format_search_results(query: str, hits: list[dict]) -> str:
    """Réponse de l'outil `search_codebase` (ADR-0013).

    Contrairement à `format_context`, c'est le modèle qui a demandé cette
    recherche : on ne lui dit pas que les passages peuvent être hors sujet ni
    de les ignorer (essai réel du 2026-10-14).
    """
    if not hits:
        return (
            f'[Recherche "{query}" : aucun passage pertinent dans le projet.] '
            "Essaie d'autres mots, ou dis que tu n'as pas trouvé l'information."
        )
    parts = [
        f'[Recherche "{query}" : {len(hits)} passage(s) du projet.] Cite tes '
        "sources sous la forme fichier:ligne, en lisant le numéro écrit en début de ligne."
    ]
    for hit in hits:
        parts.append(f"--- {hit['source']}:{hit['start']}-{hit['end']}\n{_numbered(hit)}")
    return "\n\n".join(parts)
