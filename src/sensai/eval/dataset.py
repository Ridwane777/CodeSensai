"""
Jeu de données d'évaluation (JSONL, une question par ligne) — feature [EV1],
ADR-0019.

    {"id": "cas-1", "question": "...",
     "answer": "...",                       réponse à juger (sinon --generate)
     "sources": ["texte", {"source": "src/a.py", "text": "..."}],
     "notes": "ce que le cas doit montrer"}

Seuls `id` et `question` sont obligatoires. Une clé inconnue est une erreur : une
faute de frappe (`anwser`) ferait sinon juger un cas sans sa réponse. Chaque
erreur donne le numéro de ligne du fichier.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALLOWED_KEYS = {"id", "question", "answer", "sources", "notes"}


class DatasetError(ValueError):
    """Fichier illisible ou ligne invalide (le message nomme la ligne)."""


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    answer: str | None = None
    sources: list[str | dict[str, Any]] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class Dataset:
    path: str
    sha256: str
    cases: list[Case]


def _text(record: dict, key: str, line: int, required: bool = False) -> str | None:
    value = record.get(key)
    if value is None:
        if required:
            raise DatasetError(f"ligne {line} : « {key} » est obligatoire")
        return None
    if not isinstance(value, str):
        raise DatasetError(f"ligne {line} : « {key} » doit être une chaîne")
    if not value.strip():
        if required:
            raise DatasetError(f"ligne {line} : « {key} » ne doit pas être vide")
        return None
    return value


def _sources(record: dict, line: int) -> list[str | dict[str, Any]]:
    raw = record.get("sources")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DatasetError(f"ligne {line} : « sources » doit être une liste")
    sources: list[str | dict[str, Any]] = []
    for n, item in enumerate(raw, start=1):
        if isinstance(item, str) and item.strip():
            sources.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            if not isinstance(item.get("source", ""), str):
                raise DatasetError(f"ligne {line} : sources[{n}] « source » doit être une chaîne")
            sources.append({"source": item.get("source", ""), "text": item["text"]})
        else:
            raise DatasetError(
                f"ligne {line} : sources[{n}] doit être un texte ou {{\"source\", \"text\"}}"
            )
    return sources


def load_dataset(path: str | Path) -> Dataset:
    """Lit le fichier ; DatasetError au premier problème (avec la ligne)."""
    try:
        data = Path(path).read_bytes()
        content = data.decode("utf-8")
    except OSError as e:
        raise DatasetError(f"jeu de données illisible : {e}") from e
    except UnicodeDecodeError as e:
        raise DatasetError(f"jeu de données : le fichier doit être en UTF-8 ({e})") from e

    cases: list[Case] = []
    first_line: dict[str, int] = {}
    for line, text in enumerate(content.splitlines(), start=1):
        if not text.strip():
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as e:
            raise DatasetError(f"ligne {line} : JSON invalide ({e.msg})") from e
        if not isinstance(record, dict):
            raise DatasetError(f"ligne {line} : chaque ligne doit être un objet JSON")
        unknown = sorted(set(record) - ALLOWED_KEYS)
        if unknown:
            raise DatasetError(
                f"ligne {line} : clé inconnue {', '.join(unknown)} "
                f"(clés admises : {', '.join(sorted(ALLOWED_KEYS))})"
            )
        case_id = _text(record, "id", line, required=True)
        if case_id in first_line:
            raise DatasetError(
                f"ligne {line} : id « {case_id} » déjà utilisé à la ligne {first_line[case_id]}"
            )
        first_line[case_id] = line
        cases.append(
            Case(
                id=case_id,
                question=_text(record, "question", line, required=True),
                answer=_text(record, "answer", line),
                sources=_sources(record, line),
                notes=_text(record, "notes", line) or "",
            )
        )
    if not cases:
        raise DatasetError("jeu de données vide : aucune ligne")
    return Dataset(path=str(path), sha256=hashlib.sha256(data).hexdigest(), cases=cases)
