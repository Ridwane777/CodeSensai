"""
Quality page (EV4, Workstream B) and turn log (EV3, Workstream D), server side:
routes, and log writing by the web turn loop.
"""
import threading
import time

import requests

from sensai.core.events import Done, Token, ToolCall, ToolReturn
from sensai.core.tools import ToolResult
from sensai.web.runtime import Handoffs, _AnnouncedDelegate


def test_routes_require_the_token(env):
    for path in ("/api/quality/adversarial", "/api/journal?session=x", "/api/journal/metrics"):
        assert requests.get(env.base + path, timeout=5).status_code == 401
    assert requests.post(env.base + "/api/quality/adversarial/run", timeout=5).status_code == 401


def test_without_a_run_the_committed_results_are_served(env):
    body = env.get("/api/quality/adversarial").json()
    assert body["source"] == "committed" and body["ran_at"] is None
    assert body["summary"]["total"] == 85 and body["summary"]["regressions"] == 0
    case = body["cases"][0]
    assert set(case) == {"id", "category", "attempt", "expected", "observed", "verdict", "detail"}


def test_rerun_replays_the_real_corpus(env):
    body = env.post("/api/quality/adversarial/run").json()
    assert body["source"] == "run" and body["ran_at"]
    assert body["summary"]["total"] == 85
    assert body["summary"]["regressions"] == 0 and body["summary"]["fixed"] == 0
    assert env.get("/api/quality/adversarial").json()["ran_at"] == body["ran_at"]


def test_a_second_run_during_the_first_returns_409(make_env):
    release = threading.Event()

    def slow():
        release.wait(5)
        return {"cases": [], "summary": {"total": 0}, "ran_at": "t", "source": "run"}

    env = make_env(adversarial_runner=slow)
    first = {}
    t = threading.Thread(target=lambda: first.update(r=env.post("/api/quality/adversarial/run")))
    t.start()
    time.sleep(0.3)
    second = env.post("/api/quality/adversarial/run")
    release.set()
    t.join(5)
    assert second.status_code == 409 and second.json()["code"] == "ALREADY_RUNNING"
    assert first["r"].status_code == 200 and first["r"].json()["ran_at"] == "t"


def test_a_web_turn_writes_the_log(env):
    env.script.steps = [("call", "read_file", {"path": "notes.md"}), Token("Read."),
                        Done("final_answer")]
    session_id = env.session()
    env.stream(session_id, "Read notes.md")
    body = env.get(f"/api/journal?session={session_id}").json()
    [turn] = body["turns"]
    assert turn["interface"] == "web" and turn["outcome"] == "final_answer"
    assert turn["model_ms"] is not None and turn["tokens_sent"] > 0
    [tool] = turn["tools"]
    assert tool["tool"] == "read_file" and tool["ok"] and tool["agent"] == "main"
    assert "notes.md" in tool["arguments"] and tool["duration_ms"] >= 0

    metrics = env.get("/api/journal/metrics?days=7").json()
    assert metrics["tools"][0]["tool"] == "read_file" and metrics["tools"][0]["calls"] == 1
    assert metrics["model"]["turns"] == 1


def test_deleting_the_conversation_deletes_its_log(env):
    session_id = env.session()
    env.stream(session_id, "Hello")
    assert env.get(f"/api/journal?session={session_id}").json()["turns"]
    assert env.post(f"/api/sessions/{session_id}/delete").status_code == 204
    assert env.get(f"/api/journal?session={session_id}").json()["turns"] == []


def test_subagent_tools_are_timed_and_logged():
    class Tools:
        def call(self, name, **args):
            time.sleep(0.02)
            return ToolResult(ok=True, content="content")

        def describe_all(self):
            return []

    def subagent(host, model, messages, tools):
        yield ToolCall(id="s1", name="read_file", arguments={"path": "notes.md"})
        result = tools.call("read_file", path="notes.md")
        yield ToolReturn(id="s1", name="read_file", ok=result.ok, content=result.content)
        yield Token("Read.")
        yield Done("final_answer")

    sent, noted = [], []

    class Recorder:
        def subagent_call(self, *args):
            noted.append(args)

    handoffs = Handoffs(sent.append, Recorder())
    delegate = _AnnouncedDelegate("h", "m", Tools(), run_turn=subagent, handoffs=handoffs)
    assert delegate.run(task="Read notes.md", role="explorateur").ok
    step = next(e for e in sent if e["type"] == "subagent_step")
    assert step["duration_ms"] >= 15
    [(tool, _args, ok, ms, agent)] = noted
    assert (tool, ok, agent) == ("read_file", True, "explorateur") and ms >= 15
