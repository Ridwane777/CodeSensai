"""
Evaluation dataset (JSONL, one question per line) - feature [EV1],
ADR-0019.

    {"id": "cas-1", "question": "...",
     "answer": "...",                       answer to judge (otherwise --generate)
     "sources": ["text", {"source": "src/a.py", "text": "..."}],
     "notes": "what the case must show"}

Only `id` and `question` are required. An unknown key is an error: a typo
(`anwser`) would otherwise judge a case without its answer. Every error gives
the file's line number.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALLOWED_KEYS = {"id", "question", "answer", "sources", "notes"}


class DatasetError(ValueError):
    """Unreadable file or invalid line (the message names the line)."""


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
            raise DatasetError(f"line {line}: \"{key}\" is required")
        return None
    if not isinstance(value, str):
        raise DatasetError(f"line {line}: \"{key}\" must be a string")
    if not value.strip():
        if required:
            raise DatasetError(f"line {line}: \"{key}\" must not be empty")
        return None
    return value


def _sources(record: dict, line: int) -> list[str | dict[str, Any]]:
    raw = record.get("sources")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DatasetError(f"line {line}: \"sources\" must be a list")
    sources: list[str | dict[str, Any]] = []
    for n, item in enumerate(raw, start=1):
        if isinstance(item, str) and item.strip():
            sources.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            if not isinstance(item.get("source", ""), str):
                raise DatasetError(f"line {line}: sources[{n}] \"source\" must be a string")
            sources.append({"source": item.get("source", ""), "text": item["text"]})
        else:
            raise DatasetError(
                f"line {line}: sources[{n}] must be a text or {{\"source\", \"text\"}}"
            )
    return sources


def load_dataset(path: str | Path) -> Dataset:
    """Reads the file; DatasetError on the first problem (with the line)."""
    try:
        data = Path(path).read_bytes()
        content = data.decode("utf-8")
    except OSError as e:
        raise DatasetError(f"unreadable dataset: {e}") from e
    except UnicodeDecodeError as e:
        raise DatasetError(f"dataset: the file must be UTF-8 ({e})") from e

    cases: list[Case] = []
    first_line: dict[str, int] = {}
    for line, text in enumerate(content.splitlines(), start=1):
        if not text.strip():
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as e:
            raise DatasetError(f"line {line}: invalid JSON ({e.msg})") from e
        if not isinstance(record, dict):
            raise DatasetError(f"line {line}: each line must be a JSON object")
        unknown = sorted(set(record) - ALLOWED_KEYS)
        if unknown:
            raise DatasetError(
                f"line {line}: unknown key {', '.join(unknown)} "
                f"(allowed keys: {', '.join(sorted(ALLOWED_KEYS))})"
            )
        case_id = _text(record, "id", line, required=True)
        if case_id in first_line:
            raise DatasetError(
                f"line {line}: id \"{case_id}\" already used on line {first_line[case_id]}"
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
        raise DatasetError("empty dataset: no line")
    return Dataset(path=str(path), sha256=hashlib.sha256(data).hexdigest(), cases=cases)
