"""
Le vrai serveur web (`sensai.web`), démarré sur un port libre avec un faux modèle.

Le faux modèle (`Script`) est un `run_turn` : il reçoit la vraie passerelle et
peut appeler les vrais outils (`write_file` déclenche donc la vraie
confirmation web). Les embeddings sont simulés (`FauxEmbedder`) : ni Ollama ni
Docker ne sont nécessaires.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import requests

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
import uvicorn

from sensai.core.events import Done, Event, Token, ToolCall, ToolReturn
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.tool_policy import ToolPreferences
from sensai.web.runtime import WebRuntime
from sensai.web.server import create_app
from tests.knowledge.test_rag import FauxEmbedder

TOKEN = "jeton-de-test"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Script:
    """Faux modèle : rejoue `steps` et note ce qu'il a reçu.

    Chaque étape est un événement, ou ("call", outil, arguments) pour appeler
    un outil à travers la passerelle (comme la vraie boucle).
    """

    def __init__(self) -> None:
        self.steps: list[Any] = [Token("Bonjour."), Done("final_answer")]
        self.calls: list[list[dict]] = []
        self.pause = 0.0
        self.raise_error = False

    def __call__(self, host: str, model: str, messages: list[dict], tools: Any) -> Iterator[Event]:
        self.calls.append(messages)
        if self.raise_error:
            raise RuntimeError("bug du cœur")
        for step in self.steps:
            if self.pause:
                time.sleep(self.pause)
            if isinstance(step, tuple) and step[0] == "call":
                _, name, args = step
                yield ToolCall(id="c1", name=name, arguments=args)
                result = tools.call(name, **args)
                yield ToolReturn(id="c1", name=name, ok=result.ok, content=result.content)
            else:
                yield step


class Env:
    def __init__(self, root: Path, *, rag: bool = False, cache: bool = False,
                 confirm_timeout_s: float = 5.0, blocklist: list | None = None,
                 frontend_dir: Path | None = None, personas: Any = None,
                 prompt_store: Any = None,
                 adversarial_runner: Callable[[], dict] | None = None,
                 share_links: bool = True) -> None:
        self.project = root / "projet"
        self.project.mkdir(parents=True)
        (self.project / "notes.md").write_text(
            "# Tests\nLancer les tests avec pytest -q.\n", encoding="utf-8")
        self.script = Script()
        self.settings = {
            "model": "faux-modele",
            "host": "http://127.0.0.1:1",
            "system_prompt": "Tu es CodeSensei.",
            "memory_prompt": "Conversation reprise.",
            "data_dir": str(root / "donnees"),
            "retention_days": 30,
            "rag": rag,
            "rag_model": "bge-m3",
            "rag_min_score": 0.0,
            "rag_top_k": 3,
            "rag_rerank": False,
            "cache": cache,
            "tool_preferences": ToolPreferences(confirm_timeout_s=confirm_timeout_s),
            "file_permissions": FilePermissions.for_workspace(self.project),
            "input_blocklist": blocklist,
            "share_links": share_links,
        }
        if personas is not None:
            self.settings["personas"] = personas
        self.runtime = WebRuntime(self.settings, self.project, run_turn=self.script,
                                  embedder_factory=lambda host, model: FauxEmbedder(),
                                  converter_factory=lambda: None, reranker_factory=None,
                                  prompt_store=prompt_store)
        self.app = create_app(self.runtime, token=TOKEN, frontend_dir=frontend_dir,
                              allowed_origins=["http://allowed.example"],
                              adversarial_runner=adversarial_runner)
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                                    log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            try:
                if requests.get(f"{self.base}/api/health", timeout=1).ok:
                    break
            except requests.RequestException:
                time.sleep(0.05)
        else:
            raise RuntimeError("le serveur n'a pas démarré")

    # --- appels -------------------------------------------------------------------

    def headers(self, token: str | None = TOKEN) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}

    def get(self, path: str, **kw: Any) -> requests.Response:
        return requests.get(self.base + path, headers=self.headers(), timeout=10, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> requests.Response:
        return requests.post(self.base + path, json=body, headers=self.headers(), timeout=10, **kw)

    def session(self) -> str:
        return self.post("/api/sessions").json()["session_id"]

    def stream(self, session_id: str, content: str,
               on_event: Callable[[dict], None] | None = None, *, keep_usage: bool = False,
               **extra: Any) -> list[dict]:
        """Envoie un message et lit tout le flux ; `on_event` peut répondre en cours de route.

        `usage` (M2) arrive à chaque tour avant la réponse : écarté par défaut pour
        que les tests vérifient l'ordre des autres événements ; `keep_usage=True` le garde.
        """
        events = []
        with requests.post(f"{self.base}/api/sessions/{session_id}/messages",
                           json={"content": content, **extra}, headers=self.headers(),
                           stream=True, timeout=30) as response:
            assert response.status_code == 200, response.text
            for line in response.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    event = json.loads(line[5:])
                    if event.get("type") == "usage" and not keep_usage:
                        continue
                    events.append(event)
                    if on_event:
                        on_event(event)
        return events

    def close(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture
def make_env(tmp_path):
    envs: list[Env] = []

    def _make(**kw: Any) -> Env:
        env = Env(tmp_path / f"e{len(envs)}", **kw)
        envs.append(env)
        return env

    yield _make
    for env in envs:
        env.close()


@pytest.fixture
def env(make_env):
    return make_env()


def types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]
