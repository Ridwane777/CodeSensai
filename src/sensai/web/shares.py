"""
[Workstream D] Conversation share links - feature [X3] Export & Publishing (ADR-0048).

A link = a random token (`secrets.token_urlsafe`, 256 bits) that opens a
read-only page, without authentication: `GET /share/<token>`.

- Snapshot: the conversation is copied at share time, with secrets masked
  (same filters as the export, EV2). Anything said afterwards is not published.
- The file only keeps the SHA-256 digest of the token: someone who reads it
  cannot rebuild the links.
- Each link expires (7 days by default) and can be revoked; expired links
  are deleted at startup.

Format of `<data_dir>/shares.json`:
    {"<sha256 of the token>": {"session_id": "...", "created_at": "2026-10-29T15:00:00+00:00",
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

    # --- file --------------------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"{self.path}: expected a JSON object")
        return data

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)  # conversations: readable by their owner only
        tmp.replace(self.path)

    @staticmethod
    def _expired(entry: dict[str, Any], now: datetime) -> bool:
        try:
            return datetime.fromisoformat(entry["expires_at"]) <= now
        except (KeyError, TypeError, ValueError):
            return True  # corrupted entry: never served

    # --- API -----------------------------------------------------------------------

    def create(self, session_id: str, turns: list[dict]) -> dict[str, str]:
        """Publish a filtered snapshot; return the token (shown only once) and the expiry."""
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
        """The snapshot of a valid link, or None (unknown, revoked or expired)."""
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
        """Delete expired links; return how many."""
        now = _now()
        with self._lock:
            data = self._load()
            kept = {k: v for k, v in data.items() if not self._expired(v, now)}
            if len(kept) != len(data):
                self._save(kept)
            return len(data) - len(kept)
