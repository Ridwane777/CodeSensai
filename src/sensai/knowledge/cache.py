"""
[Lot C — Ridwane] Cache sémantique des réponses — feature [A6].

Les embeddings captent le thème d'une question, pas le mot qui en change le
sens : avec bge-m3, « taille maximale » et « taille minimale d'un fichier
indexé » ont une similarité de 0,92, plus que la plupart des vraies
reformulations (docs/performance/A6-cache.md). Une similarité seule ne suffit
donc pas : `conflict` refuse deux questions qui ne portent pas sur les mêmes
noms (identifiants du code, langages, outils) ou pas sur la même action.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from sensai.knowledge.memory import ensure_private_dir, restrict_file

# Familles d'actions courantes dans les questions de développeurs. Deux
# questions dont les actions diffèrent n'appellent pas la même réponse
# (« ajouter » et « supprimer un utilisateur »). Racines sans accents ; une
# racine de 4 lettres ou plus couvre ses dérivés (« supprim » : supprimer,
# suppression), une racine plus courte doit être le mot entier.
ACTIONS: dict[str, tuple[str, ...]] = {
    "create": ("ajout", "ajoute", "creer", "creat", "cree", "nouveau", "nouvel", "nouvelle",
               "add", "create", "new"),
    "read": ("lire", "lis", "lit", "lecture", "read"),
    "write": ("ecrire", "ecrit", "ecriture", "write", "sauvegard", "save", "enregistr"),
    "update": ("modifi", "changer", "change", "edit", "update", "renomm", "rename", "jour"),
    "delete": ("supprim", "effac", "retir", "delete", "remove", "drop", "vider"),
    "enable": ("activ", "enable", "actif", "active"),
    "disable": ("desactiv", "disable", "inactif"),
    "start": ("demarr", "lanc", "start", "run", "execut", "tourn", "ouvr", "open",
              "connect", "connecter"),
    "stop": ("arret", "stop", "ferm", "close", "kill"),
    "install": ("install",),
    "uninstall": ("desinstall", "uninstall"),
    "more": ("max", "maximal", "maximum", "augment", "allong", "increase"),
    "less": ("min", "minimal", "minimum", "redui", "reduc", "diminu", "decrease"),
    "import": ("import",),
    "export": ("export",),
    "publish": ("publi", "deploi", "deploy"),
    "merge": ("fusion", "merge"),
    "count": ("compt", "count"),
    "list": ("lister", "liste", "list", "enumer"),
    "build": ("gener", "construi", "build", "compil"),
}

_WORD = re.compile(r"[\w.-]+")


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def actions(question: str) -> set[str]:
    """Familles d'actions présentes dans la question."""
    found = set()
    for word in re.findall(r"[a-z]+", _plain(question)):
        for family, roots in ACTIONS.items():
            if any(word.startswith(r) if len(r) >= 4 else word == r for r in roots):
                found.add(family)
    return found


def names(question: str) -> set[str]:
    """Noms propres et identifiants : `purge_sessions`, `KeyError`, Python, CI, 3.12.

    Un mot compte s'il contient `_`, un chiffre ou une majuscule ailleurs qu'en
    première lettre de la question.
    """
    found = set()
    for position, word in enumerate(_WORD.findall(question)):
        word = word.strip(".-")
        if not word:
            continue
        if ("_" in word or any(c.isdigit() for c in word)
                or any(c.isupper() for c in word[1:])
                or (position > 0 and word[0].isupper())):
            found.add(_plain(word))
    return found


def conflict(cached: str, asked: str) -> str | None:
    """Raison pour laquelle `asked` ne doit pas recevoir la réponse de `cached`, ou None."""
    if names(cached) != names(asked):
        return "noms différents"
    if actions(cached) != actions(asked):
        return "actions différentes"
    return None


# --- Questions qui dépendent de la conversation -------------------------------

# Mots qui renvoient à ce qui précède : la même phrase n'a pas le même sens
# d'une conversation à l'autre, elle n'est donc ni servie ni enregistrée.
_DEICTIC_WORDS = frozenset({
    "ca", "cela", "ceci", "cette", "ces", "ci", "dessus", "precedent", "precedente",
    "ensuite", "encore", "pareil", "idem", "this", "that", "it", "above", "previous",
    "again", "then",
})
_DEICTIC_PHRASES = ("ce code", "ce fichier", "ce que", "ce qu", "tu viens", "et si")
MIN_WORDS = 3


def standalone(question: str) -> bool:
    """La question se comprend-elle seule, hors de la conversation en cours ?"""
    plain = _plain(question)
    words = re.findall(r"[a-z0-9_]+", plain)
    if len(words) < MIN_WORDS:
        return False
    if _DEICTIC_WORDS.intersection(words):
        return False
    padded = f" {' '.join(words)} "
    return not any(f" {phrase} " in padded for phrase in _DEICTIC_PHRASES)


# --- Le cache -----------------------------------------------------------------

CACHE_FILE = "cache.db"
DEFAULT_THRESHOLD = 0.90  # mesuré (ADR-0033) : piège le plus fort à 0,876
DEFAULT_TTL_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS answer_cache (
    id INTEGER PRIMARY KEY,
    project TEXT NOT NULL,
    model TEXT NOT NULL,
    question TEXT NOT NULL,
    vector BLOB NOT NULL,
    answer TEXT NOT NULL,
    sources TEXT NOT NULL,
    created_at TEXT NOT NULL,
    seconds REAL NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS answer_cache_scope ON answer_cache (project, model);
"""


@dataclass
class CachedAnswer:
    question: str
    answer: str
    created_at: datetime
    similarity: float


def _digest(path: Path) -> str:
    """Empreinte du contenu, ou "" si le fichier n'existe pas."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


class AnswerCache:
    """Réponses déjà données, servies à une question de même sens (A6, ADR-0033).

    Une entrée est propre à un projet et au modèle de chat qui a répondu. Elle
    n'est servie que si la similarité atteint `threshold`, que `conflict` ne
    trouve aucun mot décisif différent, qu'elle a moins de `ttl_days` jours et
    que les fichiers du projet dont la réponse s'est servie n'ont pas changé.
    """

    def __init__(self, db_path: str | Path, project: str, embed: Callable[[list[str]], list],
                 model: str, threshold: float = DEFAULT_THRESHOLD,
                 ttl_days: int = DEFAULT_TTL_DAYS,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.db_path = Path(db_path)
        self.project = project
        self.embed = embed
        self.model = model
        self.threshold = threshold
        self.ttl = timedelta(days=ttl_days)
        self.now = now
        ensure_private_dir(self.db_path.parent)
        is_new = not self.db_path.exists()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
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

    def _vector(self, text: str) -> np.ndarray:
        vector = np.asarray(self.embed([text])[0], dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def _fresh(self, sources: dict[str, str]) -> bool:
        root = Path(self.project)
        return all(_digest(root / path) == digest for path, digest in sources.items())

    def lookup(self, question: str) -> CachedAnswer | None:
        """La réponse en cache pour `question`, ou None s'il y a le moindre doute."""
        if not standalone(question):
            return None
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, question, vector, answer, sources, created_at FROM answer_cache "
                "WHERE project = ? AND model = ?", (self.project, self.model)).fetchall()
        if not rows:
            return None
        query = self._vector(question)
        scored = []
        for row in rows:
            vector = np.frombuffer(row[2], dtype=np.float32)
            if vector.shape == query.shape:
                scored.append((float(vector @ query), row))
        limit = self.now() - self.ttl
        for similarity, (entry_id, cached, _, answer, sources, created) in sorted(
                scored, key=lambda pair: -pair[0]):
            if similarity < self.threshold:
                break
            if conflict(cached, question):
                continue
            created_at = datetime.fromisoformat(created)
            if created_at < limit or not self._fresh(json.loads(sources)):
                with self._connect() as conn:
                    conn.execute("DELETE FROM answer_cache WHERE id = ?", (entry_id,))
                continue
            with self._connect() as conn:
                conn.execute("UPDATE answer_cache SET hits = hits + 1 WHERE id = ?", (entry_id,))
            return CachedAnswer(cached, answer, created_at, round(similarity, 4))
        return None

    def store(self, question: str, answer: str, sources: list[str], seconds: float) -> bool:
        """Enregistre une réponse ; False si la question dépend de la conversation."""
        if not standalone(question) or not answer.strip():
            return False
        root = Path(self.project)
        digests = {path: _digest(root / path) for path in sorted(set(sources))}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO answer_cache (project, model, question, vector, answer, sources, "
                "created_at, seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self.project, self.model, question, self._vector(question).tobytes(), answer,
                 json.dumps(digests), self.now().isoformat(), round(seconds, 2)))
        return True

    def forget(self, question: str) -> int:
        """Retire les réponses à cette question exacte (/again en redemande une)."""
        with self._connect() as conn:
            return conn.execute(
                "DELETE FROM answer_cache WHERE project = ? AND model = ? AND question = ?",
                (self.project, self.model, question)).rowcount

    def clear(self) -> int:
        with self._connect() as conn:
            return conn.execute("DELETE FROM answer_cache WHERE project = ?",
                                (self.project,)).rowcount

    def stats(self) -> dict[str, float]:
        with self._connect() as conn:
            entries, served, saved = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(hits), 0), COALESCE(SUM(hits * seconds), 0) "
                "FROM answer_cache WHERE project = ?", (self.project,)).fetchone()
        return {"entries": entries, "served": served, "seconds_saved": round(saved, 1)}


def handle_cache_command(text: str, cache: AnswerCache | None) -> str | None:
    """/cache (bilan) et /cache clear ; None si `text` n'est pas une de ces commandes."""
    command = text.strip().lower()
    if command not in ("/cache", "/cache clear"):
        return None
    if cache is None:
        return "Cache des réponses désactivé (--no-cache, ou embeddings indisponibles)."
    if command == "/cache clear":
        return f"Cache vidé : {cache.clear()} réponse(s) retirée(s)."
    stats = cache.stats()
    return (f"Cache des réponses : {stats['entries']} réponse(s) en mémoire, servie(s) "
            f"{stats['served']} fois, environ {stats['seconds_saved']:.0f} s gagnées. "
            "/cache clear pour le vider, /again pour redemander au modèle.")
