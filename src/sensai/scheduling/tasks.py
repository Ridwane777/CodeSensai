"""
Tâches planifiées et leur stockage — feature [X5], ADR-0016.

Une tâche = un prompt rejoué à intervalle fixe. Tout est dans un seul fichier
JSON (`<données>/schedule/tasks.json`) : quelques tâches par utilisateur, donc
rien qui justifie une base de données (voir l'ADR).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

TASKS_FILE = "tasks.json"
# Un identifiant sert de nom de dossier et de fichier verrou : alphabet restreint,
# pour qu'aucun identifiant ne puisse sortir du dossier (« ../x »).
ID_PATTERN = re.compile(r"[a-z0-9-]{1,40}")
# En dessous d'une minute, une tâche se chevaucherait elle-même et saturerait Ollama.
MIN_INTERVAL_S = 60
DEFAULT_TIMEOUT_S = 600

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_INTERVAL = re.compile(r"(\d+)\s*([smhd]?)")


class ScheduleStoreError(Exception):
    """Le fichier des tâches est illisible ou n'a pas le bon format.

    Le fichier n'est jamais réécrit dans ce cas : il contient peut-être des
    tâches récupérables à la main.
    """


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_interval(text: str | int) -> int:
    """« 30m », « 1h », « 1d », « 7d » ou un nombre de secondes -> secondes.

    Refuse tout ce qui est inférieur à MIN_INTERVAL_S.
    """
    if isinstance(text, bool):
        raise ValueError("Intervalle invalide.")
    if isinstance(text, int):
        seconds = text
    else:
        match = _INTERVAL.fullmatch(text.strip().lower())
        if match is None:
            raise ValueError(
                f"Intervalle invalide : {text!r} (exemples : 300, 30m, 1h, 1d, 7d)."
            )
        seconds = int(match.group(1)) * _UNITS[match.group(2) or "s"]
    if seconds < MIN_INTERVAL_S:
        raise ValueError(f"Intervalle trop court : {MIN_INTERVAL_S} secondes au minimum.")
    return seconds


def format_interval(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def validate_task_id(task_id: str) -> str:
    if not isinstance(task_id, str) or ID_PATTERN.fullmatch(task_id) is None:
        raise ValueError(
            f"Identifiant invalide : {task_id!r} (1 à 40 caractères parmi a-z, 0-9 et « - »)."
        )
    return task_id


def parse_time(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    # Une date sans fuseau est lue comme UTC : on ne mélange jamais naïf et aware.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass
class Task:
    id: str
    prompt: str
    interval_s: int
    enabled: bool = True
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    last_run_at: str | None = None
    last_status: str | None = None
    # None = tous les outils du registre ; sinon la liste de ceux qu'on garde.
    tools: list[str] | None = None
    timeout_s: int = DEFAULT_TIMEOUT_S

    def is_due(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        due_at = self.next_due()
        return due_at is None or now >= due_at

    def next_due(self) -> datetime | None:
        """Prochaine échéance, ou None si la tâche n'a jamais tourné (due tout de suite)."""
        if self.last_run_at is None:
            return None
        return parse_time(self.last_run_at) + timedelta(seconds=self.interval_s)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "prompt": self.prompt,
            "interval_s": self.interval_s,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "timeout_s": self.timeout_s,
        }
        if self.tools is not None:
            data["tools"] = list(self.tools)
        return data

    @classmethod
    def from_dict(cls, data: Any) -> Task:
        """Lève ValueError si `data` n'a pas le format attendu."""
        if not isinstance(data, dict):
            raise ValueError("une tâche doit être un objet JSON")
        unknown = set(data) - {f for f in cls.__dataclass_fields__}
        if unknown:
            raise ValueError(f"clés inconnues : {sorted(unknown)}")
        task_id = validate_task_id(data.get("id"))  # type: ignore[arg-type]
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"tâche {task_id} : 'prompt' doit être un texte non vide")
        interval = data.get("interval_s")
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < MIN_INTERVAL_S:
            raise ValueError(
                f"tâche {task_id} : 'interval_s' doit être un entier >= {MIN_INTERVAL_S}"
            )
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"tâche {task_id} : 'enabled' doit être true ou false")
        created = data.get("created_at")
        last_run = data.get("last_run_at")
        for key, value in (("created_at", created), ("last_run_at", last_run)):
            if value is None and key == "last_run_at":
                continue
            try:
                parse_time(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                raise ValueError(f"tâche {task_id} : '{key}' n'est pas une date ISO") from None
        status = data.get("last_status")
        if status is not None and not isinstance(status, str):
            raise ValueError(f"tâche {task_id} : 'last_status' doit être un texte")
        tools = data.get("tools")
        if tools is not None and (
            not isinstance(tools, list) or not all(isinstance(t, str) for t in tools)
        ):
            raise ValueError(f"tâche {task_id} : 'tools' doit être une liste de noms d'outils")
        timeout = data.get("timeout_s", DEFAULT_TIMEOUT_S)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise ValueError(f"tâche {task_id} : 'timeout_s' doit être un entier > 0")
        return cls(
            id=task_id,
            prompt=prompt,
            interval_s=interval,
            enabled=enabled,
            created_at=created,
            last_run_at=last_run,
            last_status=status,
            tools=tools,
            timeout_s=timeout,
        )


def atomic_write(path: Path, text: str) -> None:
    """Écriture atomique : fichier temporaire du même dossier, puis os.replace.

    Un plantage (ou un autre processus qui lit) ne voit jamais un fichier
    à moitié écrit.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> list[Task]:
        """Les tâches ; liste vide si le fichier n'existe pas encore.

        Lève ScheduleStoreError si le fichier est cassé — sans y toucher.
        """
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeDecodeError) as exc:
            raise ScheduleStoreError(f"{self.path} illisible : {exc}") from exc
        try:
            items = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ScheduleStoreError(f"{self.path} n'est pas du JSON valide : {exc}") from exc
        if not isinstance(items, list):
            raise ScheduleStoreError(f"{self.path} : une liste de tâches était attendue")
        tasks: list[Task] = []
        for item in items:
            try:
                tasks.append(Task.from_dict(item))
            except ValueError as exc:
                raise ScheduleStoreError(f"{self.path} : {exc}") from exc
        ids = [t.id for t in tasks]
        if len(set(ids)) != len(ids):
            raise ScheduleStoreError(f"{self.path} : identifiants de tâche en double")
        return tasks

    def save(self, tasks: list[Task]) -> None:
        """Écrit toutes les tâches d'un coup (atomic_write)."""
        payload = json.dumps([t.to_dict() for t in tasks], ensure_ascii=False, indent=2)
        atomic_write(self.path, payload + "\n")

    def get(self, task_id: str) -> Task | None:
        return next((t for t in self.load() if t.id == task_id), None)

    def add(self, task: Task) -> None:
        tasks = self.load()
        if any(t.id == task.id for t in tasks):
            raise ValueError(f"Une tâche « {task.id} » existe déjà.")
        tasks.append(task)
        self.save(tasks)

    def remove(self, task_id: str) -> bool:
        tasks = self.load()
        kept = [t for t in tasks if t.id != task_id]
        if len(kept) == len(tasks):
            return False
        self.save(kept)
        return True

    def update(self, task_id: str, **changes: Any) -> bool:
        """Modifie une tâche en relisant le fichier juste avant : une tâche ajoutée
        pendant qu'une autre tourne n'est pas écrasée. False si elle a disparu."""
        tasks = self.load()
        for task in tasks:
            if task.id == task_id:
                for key, value in changes.items():
                    setattr(task, key, value)
                self.save(tasks)
                return True
        return False
