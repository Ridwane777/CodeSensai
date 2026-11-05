"""
Vérifie, de bout en bout, le comportement décrit par docs/architecture/web-api.md sur le prototype
docs/conception/web_facade_spike.py : vraie boucle d'agent, vraie passerelle d'outils, faux Ollama.

Ignoré quand fastapi, uvicorn ou httpx manquent (ils ne sont pas dans les dépendances du projet).
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

SPIKE = Path(__file__).resolve().parents[2] / "docs" / "conception" / "web_facade_spike.py"
spec = importlib.util.spec_from_file_location("web_facade_spike", SPIKE)
spike = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = spike  # requis avant exec_module : @dataclass relit le module par son nom
spec.loader.exec_module(spike)

TOKEN = "jeton-de-test"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WriteTool:
    """Outil à risque « write » : la passerelle doit demander confirmation avant de l'exécuter."""

    name = "demo_write"
    description = "Écrit un fichier (démonstration)."
    risk = "write"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(self) -> None:
        self.runs = 0

    def describe_call(self, **args: Any) -> str:
        return f"Écrire {args.get('path')}"

    def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        return ToolResult(ok=True, content="écrit")


class FakeOllama(BaseHTTPRequestHandler):
    """Rejoue des réponses scénarisées au format NDJSON d'Ollama, selon le dernier message."""

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
            self._send([{"message": {"content": "Terminé."}, "done": False}, done])
            return
        text = last["content"]
        if "echo" in text:
            call = {"function": {"name": "echo", "arguments": {"text": "salut"}}}
            self._send([{"message": {"tool_calls": [call]}, "done": True}])
        elif "ecris" in text:
            call = {"function": {"name": "demo_write", "arguments": {"path": "a.txt"}}}
            self._send([{"message": {"tool_calls": [call]}, "done": True}])
        elif "lent" in text:
            words = [{"message": {"content": f"mot{i} "}, "done": False} for i in range(40)]
            self._send([*words, done], pause=0.1)
        else:
            self._send([{"message": {"content": "Bon"}, "done": False},
                        {"message": {"content": "jour"}, "done": False}, done])


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
    """Joue un tour ; répond à la confirmation (True/False) ou ne répond pas (None)."""
    seen: list[dict] = []
    for event in events(env.stream(session, text)):
        seen.append(event)
        if event["type"] == "confirm_request" and approve is not None:
            assert env.confirm(session, event["confirm_id"], approve).status_code == 204
    return seen


def test_reponse_en_flux_et_done_en_dernier(env: Env) -> None:
    session = env.new_session()
    seen = list(events(env.stream(session, "bonjour")))
    assert "".join(e["text"] for e in seen if e["type"] == "token") == "Bonjour"
    assert seen[-1] == {"type": "done", "reason": "final_answer"}
    assert [e["type"] for e in seen].count("done") == 1


def test_appel_et_retour_d_outil_partagent_le_meme_id(env: Env) -> None:
    session = env.new_session()
    seen = list(events(env.stream(session, "echo")))
    call = next(e for e in seen if e["type"] == "tool_call")
    ret = next(e for e in seen if e["type"] == "tool_return")
    assert call["id"] == ret["id"] and ret["ok"] is True and ret["content"] == "salut"
    assert seen[-1]["type"] == "done"


def test_l_outil_a_risque_ne_s_execute_qu_apres_accord(env: Env) -> None:
    session = env.new_session()
    seen = run_with_answer(env, session, "ecris", approve=True)
    request = next(e for e in seen if e["type"] == "confirm_request")
    assert request["risk"] == "write" and request["tool"] == "demo_write"
    assert request["arguments"] == {"path": "a.txt"} and request["timeout_s"] == 5.0
    assert next(e for e in seen if e["type"] == "tool_return")["ok"] is True
    assert env.write_tool.runs == 1


def test_refus_n_execute_rien_et_le_tour_continue(env: Env) -> None:
    session = env.new_session()
    seen = run_with_answer(env, session, "ecris", approve=False)
    assert next(e for e in seen if e["type"] == "tool_return")["ok"] is False
    assert env.write_tool.runs == 0
    assert seen[-1] == {"type": "done", "reason": "final_answer"}


def test_pas_de_reponse_avant_le_delai_vaut_refus_et_une_reponse_tardive_est_ignoree() -> None:
    env = Env(confirm_timeout_s=0.6)
    try:
        session = env.new_session()
        seen = run_with_answer(env, session, "ecris", approve=None)
        assert next(e for e in seen if e["type"] == "tool_return")["ok"] is False
        asked = next(e for e in seen if e["type"] == "confirm_request")
        assert env.confirm(session, asked["confirm_id"], True).status_code == 404
        assert env.write_tool.runs == 0
    finally:
        env.close()


def test_une_confirmation_inconnue_est_sans_effet(env: Env) -> None:
    session = env.new_session()
    assert env.confirm(session, "inconnue", True).status_code == 404
    assert env.write_tool.runs == 0


def test_fermer_l_onglet_pendant_la_confirmation_n_execute_rien() -> None:
    env = Env(confirm_timeout_s=3.0)
    try:
        session = env.new_session()
        response = env.stream(session, "ecris")
        for event in events(response):
            if event["type"] == "confirm_request":
                break
        response.close()  # le navigateur disparaît sans répondre
        time.sleep(0.8)
        assert env.write_tool.runs == 0
    finally:
        env.close()


def test_interrompre_termine_par_done_interrupted_sans_enregistrer_le_tour(env: Env) -> None:
    session = env.new_session()
    seen: list[dict] = []
    for event in events(env.stream(session, "lent")):
        seen.append(event)
        if len(seen) == 3:
            requests.post(f"{env.base}/sessions/{session}/interrupt", headers=AUTH, timeout=5)
    assert seen[-1] == {"type": "done", "reason": "interrupted"}
    assert len([e for e in seen if e["type"] == "token"]) < 40
    history = requests.get(f"{env.base}/sessions/{session}", headers=AUTH, timeout=5).json()
    assert history["messages"] == []


def test_un_tour_reussi_entre_dans_l_historique(env: Env) -> None:
    session = env.new_session()
    list(events(env.stream(session, "bonjour")))
    saved = requests.get(f"{env.base}/sessions/{session}", headers=AUTH, timeout=5).json()
    assert saved["messages"] == [
        {"role": "user", "content": "bonjour"},
        {"role": "assistant", "content": "Bonjour"},
    ]


def test_modele_injoignable_donne_error_puis_done_et_rien_n_est_enregistre() -> None:
    env = Env(ollama_up=False)
    try:
        session = env.new_session()
        seen = list(events(env.stream(session, "bonjour")))
        assert seen[-2]["type"] == "error" and seen[-1] == {"type": "done", "reason": "error"}
        history = requests.get(f"{env.base}/sessions/{session}", headers=AUTH, timeout=5).json()
        assert history["messages"] == []
    finally:
        env.close()


def test_un_seul_tour_a_la_fois_par_session(env: Env) -> None:
    session = env.new_session()
    first = env.stream(session, "lent")
    next(events(first))  # le tour est bien lancé
    second = env.stream(session, "bonjour")
    assert second.status_code == 409
    first.close()


def test_message_vide_ou_trop_long_est_refuse_avant_le_flux(env: Env) -> None:
    session = env.new_session()
    assert env.stream(session, "   ").status_code == 400
    assert env.stream(session, "x" * (spike.MAX_MESSAGE_CHARS + 1)).status_code == 413


def test_session_inconnue_donne_404_avec_un_corps_d_erreur(env: Env) -> None:
    r = requests.get(f"{env.base}/sessions/nope", headers=AUTH, timeout=5)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_jeton_obligatoire_partout_sauf_la_sante(env: Env) -> None:
    session = env.new_session()
    for headers in ({}, {"Authorization": "Bearer faux"}, {"Authorization": "Basic abc"}):
        url = f"{env.base}/sessions/{session}/messages"
        r = requests.post(url, json={"content": "x"}, headers=headers, timeout=5)
        assert r.status_code == 401
    assert requests.post(f"{env.base}/sessions", timeout=5).status_code == 401
    assert requests.get(f"{env.base}/health", timeout=5).json() == {"status": "ok"}


def test_deux_sessions_en_parallele_ne_melangent_pas_leurs_confirmations(env: Env) -> None:
    sessions = [env.new_session(), env.new_session()]
    results: dict[str, list[dict]] = {}

    def play(session: str, approve: bool) -> None:
        results[session] = run_with_answer(env, session, "ecris", approve=approve)

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
