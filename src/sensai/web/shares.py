"""
[Lot D] Liens de partage d'une conversation — feature [X3] Export & Publication (ADR-0048).

Un lien = un jeton aléatoire (`secrets.token_urlsafe`, 256 bits) qui ouvre une
page en lecture seule, sans authentification : `GET /share/<jeton>`.

- Instantané : la conversation est copiée au moment du partage, secrets masqués
  (mêmes filtres que l'export, EV2). Ce qui est dit ensuite n'est pas publié.
- Le fichier ne garde que l'empreinte SHA-256 du jeton : quelqu'un qui le lit
  ne peut pas reconstruire les liens.
- Chaque lien expire (7 jours par défaut) et peut être révoqué ; les liens
  expirés sont effacés au démarrage.

Format de `<data_dir>/shares.json` :
    {"<sha256 du jeton>": {"session_id": "...", "created_at": "2026-10-29T15:00:00+00:00",
                           "expires_at": "...", "messages": [{"role": "user", "content": "..."}]}}
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sensai.execution.guardrails import filter_output

SHARES_FILE = "shares.json"
DEFAULT_SHARE_DAYS = 7


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


class ShareStore:
    def __init__(self, path: Path, *, days: int = DEFAULT_SHARE_DAYS) -> None:
        self.path = Path(path)
        self.days = days
        self._lock = threading.Lock()

    # --- fichier -----------------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"{self.path} : objet JSON attendu")
        return data

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)  # des conversations : lisibles par leur seul propriétaire
        tmp.replace(self.path)

    @staticmethod
    def _expired(entry: dict[str, Any], now: datetime) -> bool:
        try:
            return datetime.fromisoformat(entry["expires_at"]) <= now
        except (KeyError, TypeError, ValueError):
            return True  # entrée abîmée : jamais servie

    # --- API -----------------------------------------------------------------------

    def create(self, session_id: str, turns: list[dict]) -> dict[str, str]:
        """Publie un instantané filtré ; renvoie le jeton (montré une seule fois) et l'échéance."""
        token = secrets.token_urlsafe(32)
        now = _now()
        entry = {
            "session_id": session_id,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=self.days)).isoformat(),
            "messages": [{"role": str(t.get("role", "")),
                          "content": filter_output(str(t.get("content", "")))}
                         for t in turns if t.get("role") in ("user", "assistant")],
        }
        with self._lock:
            data = self._load()
            data[_digest(token)] = entry
            self._save(data)
        return {"token": token, "expires_at": entry["expires_at"]}

    def get(self, token: str) -> dict[str, Any] | None:
        """L'instantané d'un lien valide, ou None (inconnu, révoqué ou expiré)."""
        if not isinstance(token, str) or not token:
            return None
        with self._lock:
            entry = self._load().get(_digest(token))
        if entry is None or self._expired(entry, _now()):
            return None
        return entry

    def revoke(self, token: str) -> bool:
        with self._lock:
            data = self._load()
            if data.pop(_digest(token), None) is None:
                return False
            self._save(data)
            return True

    def purge(self) -> int:
        """Efface les liens expirés ; renvoie leur nombre."""
        now = _now()
        with self._lock:
            data = self._load()
            kept = {k: v for k, v in data.items() if not self._expired(v, now)}
            if len(kept) != len(data):
                self._save(kept)
            return len(data) - len(kept)
