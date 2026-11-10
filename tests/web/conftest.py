"""
The real web server (`sensai.web`), started on a free port with a fake model.

The fake model (`Script`) is a `run_turn`: it receives the real gateway and
can call the real tools (so `write_file` triggers the real web
confirmation). Embeddings are simulated (`FauxEmbedder`): neither Ollama nor
Docker is needed.
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

TOKEN = "test-token"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Script:
    """Fake model: replays `steps` and records what it received.

    Each step is an event, or ("call", tool, arguments) to call
    a tool through the gateway (like the real loop).
    """

    def __init__(self) -> None:
        self.steps: list[Any] = [Token("Hello."), Done("final_answer")]
        self.calls: list[list[dict]] = []
        self.pause = 0.0
        self.raise_error = False

    def __call__(self, host: str, model: str, messages: list[dict], tools: Any) -> Iterator[Event]:
        self.calls.append(messages)
        if self.raise_error:
            raise RuntimeError("core bug")
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
        self.project = root / "project"
        self.project.mkdir(parents=True)
        (self.project / "notes.md").write_text(
            "# Tests\nRun the tests with pytest -q.\n", encoding="utf-8")
        self.script = Script()
        self.settings = {
            "model": "fake-model",
            "host": "http://127.0.0.1:1",
            "system_prompt": "You are CodeSensai.",
            "memory_prompt": "Conversation resumed.",
            "data_dir": str(root / "data"),
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
            raise RuntimeError("the server did not start")

    # --- calls ---------------------------------------------------------------------

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
        """Send a message and read the whole stream; `on_event` can answer along the way.

        `usage` (M2) arrives on every turn before the answer: dropped by default so
        tests check the order of the other events; `keep_usage=True` keeps it.
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
