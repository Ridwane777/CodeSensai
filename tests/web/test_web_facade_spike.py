"""
Checks, end to end, the behavior described in docs/architecture/web-api.md on the prototype
docs/design/web_facade_spike.py: real agent loop, real tool gateway, fake Ollama.

Skipped when fastapi, uvicorn or httpx are missing (they are not project dependencies).
"""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
import requests

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
pytest.importorskip("httpx")
import uvicorn

from sensai.core.tools import ToolRegistry, ToolResult
from sensai.execution.gateway import ToolGateway
from sensai.execution.tool_policy import ToolPreferences
from sensai.tools.echo_tool import EchoTool

SPIKE = Path(__file__).resolve().parents[2] / "docs" / "design" / "web_facade_spike.py"
spec = importlib.util.spec_from_file_location("web_facade_spike", SPIKE)
spike = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = spike  # required before exec_module: @dataclass looks the module up by name
spec.loader.exec_module(spike)

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WriteTool:
    """Tool with "write" risk: the gateway must ask for confirmation before running it."""

    name = "demo_write"
    description = "Writes a file (demo)."
    risk = "write"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(self) -> None:
        self.runs = 0

    def describe_call(self, **args: Any) -> str:
        return f"Write {args.get('path')}"

    def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        return ToolResult(ok=True, content="written")


class FakeOllama(BaseHTTPRequestHandler):
    """Replays scripted answers in Ollama NDJSON format, depending on the last message."""

    def log_message(self, *args: Any) -> None:  # silence
        pass

    def _send(self, chunks: list[dict], pause: float = 0.0) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for chunk in chunks:
            try:
                self.wfile.write((json.dumps(chunk) + "\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(pause)

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        last = payload["messages"][-1]
        done = {"message": {}, "done": True}
        if last["role"] == "tool":
            self._send([{"message": {"content": "Finished."}, "done": False}, done])
            return
        text = last["content"]
        if "echo" in text:
            call = {"function": {"name": "echo", "arguments": {"text": "hi"}}}
            self._send([{"message": {"tool_calls": [call]}, "done": True}])
        elif "write" in text:
            call = {"function": {"name": "demo_write", "arguments": {"path": "a.txt"}}}
            self._send([{"message": {"tool_calls": [call]}, "done": True}])
        elif "slow" in text:
            words = [{"message": {"content": f"word{i} "}, "done": False} for i in range(40)]
            self._send([*words, done], pause=0.1)
        else:
            self._send([{"message": {"content": "Hel"}, "done": False},
                        {"message": {"content": "lo"}, "done": False}, done])


class Env:
    def __init__(self, confirm_timeout_s: float = 5.0, ollama_up: bool = True) -> None:
        self.write_tool = WriteTool()
        registry = ToolRegistry()
        registry.register(EchoTool())
        registry.register(self.write_tool)
        prefs = ToolPreferences(confirm_timeout_s=confirm_timeout_s)
        self.ollama = ThreadingHTTPServer(("127.0.0.1", free_port()), FakeOllama)
        threading.Thread(target=self.ollama.serve_forever, daemon=True).start()
        host = f"http://127.0.0.1:{self.ollama.server_address[1] if ollama_up else free_port()}"
        app = spike.create_app(
            token=TOKEN,
            host=host,
            make_gateway=lambda confirm: ToolGateway(registry, preferences=prefs, confirm=confirm),
        )
        port = free_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(config)
        threading.Thread(target=self.server.run, daemon=True).start()
        self.base = f"http://127.0.0.1:{port}/api"
        for _ in range(100):
            try:
                requests.get(f"{self.base}/health", timeout=0.5)
                break
            except requests.ConnectionError:
                time.sleep(0.05)

    def close(self) -> None:
        self.server.should_exit = True
        self.ollama.shutdown()

    def new_session(self) -> str:
        r = requests.post(f"{self.base}/sessions", headers=AUTH, timeout=5)
        assert r.status_code == 201
        return r.json()["session_id"]

    def stream(self, session: str, content: str) -> requests.Response:
        return requests.post(
            f"{self.base}/sessions/{session}/messages",
            json={"content": content},
            headers=AUTH,
            stream=True,
            timeout=30,
        )

    def confirm(self, session: str, confirm_id: str, approved: bool) -> requests.Response:
        return requests.post(
            f"{self.base}/sessions/{session}/confirm",
            json={"confirm_id": confirm_id, "approved": approved},
            headers=AUTH,
            timeout=5,
        )


def events(response: requests.Response) -> Iterator[dict]:
    for line in response.iter_lines():
        if line.startswith(b"data: "):
            yield json.loads(line[6:])


@pytest.fixture
def env() -> Iterator[Env]:
    e = Env()
    yield e
    e.close()


def run_with_answer(env: Env, session: str, text: str, approve: bool | None) -> list[dict]:
    """Plays a turn; answers the confirmation (True/False) or does not answer (None)."""
    seen: list[dict] = []
    for event in events(env.stream(session, text)):
        seen.append(event)
        if event["type"] == "confirm_request" and approve is not None:
            assert env.confirm(session, event["confirm_id"], approve).status_code == 204
    return seen


def test_streamed_answer_and_done_last(env: Env) -> None:
    session = env.new_session()
    seen = list(events(env.stream(session, "hello")))
    assert "".join(e["text"] for e in seen if e["type"] == "token") == "Hello"
    assert seen[-1] == {"type": "done", "reason": "final_answer"}
    assert [e["type"] for e in seen].count("done") == 1


def test_tool_call_and_return_share_the_same_id(env: Env) -> None:
    session = env.new_session()
    seen = list(events(env.stream(session, "echo")))
    call = next(e for e in seen if e["type"] == "tool_call")
    ret = next(e for e in seen if e["type"] == "tool_return")
    assert call["id"] == ret["id"] and ret["ok"] is True and ret["content"] == "hi"
    assert seen[-1]["type"] == "done"


def test_the_risky_tool_runs_only_after_approval(env: Env) -> None:
    session = env.new_session()
    seen = run_with_answer(env, session, "write", approve=True)
    request = next(e for e in seen if e["type"] == "confirm_request")
    assert request["risk"] == "write" and request["tool"] == "demo_write"
    assert request["arguments"] == {"path": "a.txt"} and request["timeout_s"] == 5.0
    assert next(e for e in seen if e["type"] == "tool_return")["ok"] is True
    assert env.write_tool.runs == 1


def test_refusal_runs_nothing_and_the_turn_continues(env: Env) -> None:
    session = env.new_session()
    seen = run_with_answer(env, session, "write", approve=False)
    assert next(e for e in seen if e["type"] == "tool_return")["ok"] is False
    assert env.write_tool.runs == 0
    assert seen[-1] == {"type": "done", "reason": "final_answer"}


def test_no_answer_before_timeout_is_refusal_and_late_answer_is_ignored() -> None:
    env = Env(confirm_timeout_s=0.6)
    try:
        session = env.new_session()
        seen = run_with_answer(env, session, "write", approve=None)
        assert next(e for e in seen if e["type"] == "tool_return")["ok"] is False
        asked = next(e for e in seen if e["type"] == "confirm_request")
        assert env.confirm(session, asked["confirm_id"], True).status_code == 404
        assert env.write_tool.runs == 0
    finally:
        env.close()


def test_an_unknown_confirmation_has_no_effect(env: Env) -> None:
    session = env.new_session()
    assert env.confirm(session, "unknown", True).status_code == 404
    assert env.write_tool.runs == 0


def test_closing_the_tab_during_confirmation_runs_nothing() -> None:
    env = Env(confirm_timeout_s=3.0)
    try:
        session = env.new_session()
        response = env.stream(session, "write")
        for event in events(response):
            if event["type"] == "confirm_request":
                break
        response.close()  # the browser goes away without answering
        time.sleep(0.8)
        assert env.write_tool.runs == 0
    finally:
        env.close()


def test_interrupt_ends_with_done_interrupted_without_saving_the_turn(env: Env) -> None:
    session = env.new_session()
    seen: list[dict] = []
    for event in events(env.stream(session, "slow")):
        seen.append(event)
        if len(seen) == 3:
            requests.post(f"{env.base}/sessions/{session}/interrupt", headers=AUTH, timeout=5)
    assert seen[-1] == {"type": "done", "reason": "interrupted"}
    assert len([e for e in seen if e["type"] == "token"]) < 40
    history = requests.get(f"{env.base}/sessions/{session}", headers=AUTH, timeout=5).json()
    assert history["messages"] == []


def test_a_successful_turn_enters_the_history(env: Env) -> None:
    session = env.new_session()
    list(events(env.stream(session, "hello")))
    saved = requests.get(f"{env.base}/sessions/{session}", headers=AUTH, timeout=5).json()
    assert saved["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hello"},
    ]


def test_unreachable_model_gives_error_then_done_and_nothing_is_saved() -> None:
    env = Env(ollama_up=False)
    try:
        session = env.new_session()
        seen = list(events(env.stream(session, "hello")))
        assert seen[-2]["type"] == "error" and seen[-1] == {"type": "done", "reason": "error"}
        history = requests.get(f"{env.base}/sessions/{session}", headers=AUTH, timeout=5).json()
        assert history["messages"] == []
    finally:
        env.close()


def test_one_turn_at_a_time_per_session(env: Env) -> None:
    session = env.new_session()
    first = env.stream(session, "slow")
    next(events(first))  # the turn has started
    second = env.stream(session, "hello")
    assert second.status_code == 409
    first.close()


def test_empty_or_too_long_message_is_rejected_before_the_stream(env: Env) -> None:
    session = env.new_session()
    assert env.stream(session, "   ").status_code == 400
    assert env.stream(session, "x" * (spike.MAX_MESSAGE_CHARS + 1)).status_code == 413


def test_unknown_session_gives_404_with_an_error_body(env: Env) -> None:
    r = requests.get(f"{env.base}/sessions/nope", headers=AUTH, timeout=5)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_token_required_everywhere_except_health(env: Env) -> None:
    session = env.new_session()
    for headers in ({}, {"Authorization": "Bearer fake"}, {"Authorization": "Basic abc"}):
        url = f"{env.base}/sessions/{session}/messages"
        r = requests.post(url, json={"content": "x"}, headers=headers, timeout=5)
        assert r.status_code == 401
    assert requests.post(f"{env.base}/sessions", timeout=5).status_code == 401
    assert requests.get(f"{env.base}/health", timeout=5).json() == {"status": "ok"}


def test_two_parallel_sessions_do_not_mix_their_confirmations(env: Env) -> None:
    sessions = [env.new_session(), env.new_session()]
    results: dict[str, list[dict]] = {}

    def play(session: str, approve: bool) -> None:
        results[session] = run_with_answer(env, session, "write", approve=approve)

    threads = [
        threading.Thread(target=play, args=(sessions[0], True)),
        threading.Thread(target=play, args=(sessions[1], False)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    ok = {s: next(e for e in ev if e["type"] == "tool_return")["ok"] for s, ev in results.items()}
    assert ok == {sessions[0]: True, sessions[1]: False}
    assert env.write_tool.runs == 1
