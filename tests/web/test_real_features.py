"""
What used to be simulated in the web UI and comes from the real server since 2026-10-29:
token usage (M2), state document (M4), subagent steps (A2),
few-shot (A7), on-demand evaluation (EV1) and scheduled tasks (X5).
"""
import json

from sensai.core.events import Done, Token, ToolCall, ToolReturn
from sensai.core.tools import ToolResult
from sensai.web.runtime import Handoffs, _AnnouncedDelegate

STATE = ("call", "update_state", {"section": "Decisions", "action": "append",
                                  "content": "- We keep SQLite."})


def _approve(env, session_id):
    def on_event(event):
        if event["type"] == "confirm_request":
            env.post(f"/api/sessions/{session_id}/confirm",
                     {"confirm_id": event["confirm_id"], "approved": True})
    return on_event


def test_each_turn_announces_its_estimated_usage(env):
    events = env.stream(env.session(), "Hello", keep_usage=True)
    usage = events[0]
    assert usage["type"] == "usage" and usage["estimated"] is True
    assert 0 < usage["used"] < usage["budget"] < usage["num_ctx"]


def test_a_modified_section_is_sent_to_the_artifact_panel(env):
    env.script.steps = [STATE, Token("Noted."), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Record the decision", on_event=_approve(env, session_id))
    patches = [e for e in events if e["type"] == "artifact_patch"]
    assert patches and patches[0]["section"] == "Decisions"
    assert "We keep SQLite." in patches[0]["markdown"]
    # The route returns it too, for display when the page loads.
    assert "We keep SQLite." in env.get("/api/state").json()["bodies"]["Decisions"]


def test_subagent_tools_are_published_with_its_role():
    sent = []

    class Tools:
        def call(self, name, **args):
            return ToolResult(ok=True, content="Run the tests with pytest -q.")

        def describe(self):
            return []

    def subagent(host, model, messages, tools):
        yield ToolCall(id="s1", name="read_file", arguments={"path": "notes.md"})
        result = tools.call("read_file", path="notes.md")
        yield ToolReturn(id="s1", name="read_file", ok=result.ok, content=result.content)
        yield Token("Read.")
        yield Done("final_answer")

    handoffs = Handoffs(sent.append)
    delegate = _AnnouncedDelegate("h", "m", Tools(), run_turn=subagent, handoffs=handoffs)
    assert delegate.run(task="Read notes.md", role="explorateur").ok
    assert [e["type"] for e in sent] == ["agent_handoff", "subagent_step"]
    step = sent[1]
    assert step["agent"] == "explorateur" and step["tool"] == "read_file"
    assert step["ok"] is True and "pytest" in step["content"]


def test_the_closest_few_shot_example_goes_with_the_question(env, tmp_path):
    examples = tmp_path / "examples.jsonl"
    examples.write_text(json.dumps({"id": "t", "question": "How do I run the tests?",
                                    "answer": "With pytest -q."}) + "\n", encoding="utf-8")
    env.runtime.settings.update(fewshot_examples=str(examples), fewshot_min_score=0.3)
    events = env.stream(env.session(), "How do I run the tests?")
    assert any(e["type"] == "fewshot" for e in events)
    assert "With pytest -q." in env.script.calls[-1][-1]["content"]


def test_a_missing_examples_file_becomes_a_warning(env):
    env.runtime.settings.update(fewshot_examples="does/not_exist.jsonl")
    env.stream(env.session(), "Hello")
    assert any("few-shot" in n.lower() for n in env.get("/api/config").json()["notices"])


def test_evaluate_the_last_answer(env):
    session_id = env.session()
    env.stream(session_id, "How do I run the tests?")
    judged = []

    def fake_judge(host, model, num_ctx=None):
        def judge(messages):
            judged.append(messages)
            return json.dumps({"relevance": 4, "coherence": 5, "claims": []})
        return judge

    env.runtime._judge_factory = fake_judge
    response = env.post(f"/api/sessions/{session_id}/evaluate")
    assert response.status_code == 200, response.text
    scores = response.json()["scores"]
    assert scores["relevance"] == 4 and scores["coherence"] == 5
    assert "How do I run the tests?" in json.dumps(judged[0], ensure_ascii=False)


def test_nothing_to_evaluate(env):
    response = env.post(f"/api/sessions/{env.session()}/evaluate")
    assert response.status_code == 400 and response.json()["code"] == "NOTHING_TO_EVALUATE"


def test_an_unreadable_judge_is_a_clear_error(env):
    session_id = env.session()
    env.stream(session_id, "Hello")
    env.runtime._judge_factory = lambda host, model, num_ctx=None: (lambda messages: "not json")
    response = env.post(f"/api/sessions/{session_id}/evaluate")
    assert response.status_code == 502 and response.json()["code"] == "EVALUATION_FAILED"


def test_scheduled_tasks_add_list_pause_remove(env):
    created = env.post("/api/schedule/tasks", {"id": "watch", "prompt": "Summarize the TODOs",
                                               "every": "2h"})
    assert created.status_code == 201, created.text
    assert created.json()["interval_s"] == 7200 and created.json()["next_due"] is None
    assert [t["id"] for t in env.get("/api/schedule/tasks").json()] == ["watch"]
    assert env.post("/api/schedule/tasks/watch/enabled", {"enabled": False}).status_code == 204
    assert env.get("/api/schedule/tasks").json()[0]["enabled"] is False
    # The file is the one `sensai-schedule` reads.
    assert "watch" in env.runtime.tasks.path.read_text(encoding="utf-8")
    assert env.post("/api/schedule/tasks/watch/remove").status_code == 204
    assert env.get("/api/schedule/tasks").json() == []
    assert env.post("/api/schedule/tasks/watch/remove").status_code == 404


def test_a_malformed_task_is_rejected(env):
    for body in ({"id": "a b", "prompt": "x", "every": "1h"},
                 {"id": "ok", "prompt": "  ", "every": "1h"},
                 {"id": "ok", "prompt": "x", "every": "never"}):
        response = env.post("/api/schedule/tasks", body)
        assert response.status_code == 400 and response.json()["code"] == "INVALID_TASK", body
    env.post("/api/schedule/tasks", {"id": "ok", "prompt": "x", "every": "1h"})
    assert env.post("/api/schedule/tasks", {"id": "ok", "prompt": "y", "every": "1h"}
                    ).status_code == 400


def test_few_shot_examples_are_readable_by_the_ui(env, tmp_path):
    """A7: the Prompts page shows the file, the threshold and the example questions."""
    examples = tmp_path / "examples.jsonl"
    examples.write_text(json.dumps({"id": "t", "question": "How do I run the tests?",
                                    "answer": "With pytest -q."}) + "\n", encoding="utf-8")
    assert env.get("/api/fewshot").json()["configured"] is False
    env.runtime.settings.update(fewshot_examples=str(examples), fewshot_min_score=0.3)
    info = env.get("/api/fewshot").json()
    assert info["configured"] and info["questions"] == ["How do I run the tests?"]
    assert info["min_score"] == 0.3 and info["error"] is None


def test_the_prompt_time_is_frozen_per_conversation(env, monkeypatch):
    """The first turn's time stays in the conversation's system prompt: a time that
    changed on every turn would force Ollama to reprocess the whole conversation."""
    from datetime import datetime, timedelta, timezone

    from sensai.web import runtime as runtime_module

    clock = iter([datetime(2026, 11, 1, 9, 5, tzinfo=timezone(timedelta(hours=1))),
                  datetime(2026, 11, 1, 9, 40, tzinfo=timezone(timedelta(hours=1)))])
    monkeypatch.setattr(runtime_module, "local_datetime", lambda: next(clock))
    rt = env.runtime
    first = rt.system_prompt(resumed=False, started=rt.started_at("s1"))
    assert "09:05" in first
    assert rt.system_prompt(resumed=True, started=rt.started_at("s1")).count("09:05") == 1
    assert "09:40" in rt.system_prompt(resumed=False, started=rt.started_at("s2"))


def test_preferences_come_last_in_the_prompt(env):
    """Real trial run of 2026-11-01: "always answer in English" was ignored when the profile
    was followed by the state document and the facts, written in French."""
    rt = env.runtime
    rt.profile.preferences.append("Always answer in English.")
    prompt = rt.system_prompt(resumed=False)
    assert prompt.rstrip().endswith("- Always answer in English.")
    assert prompt.index("For this session, you are") < prompt.index("## User profile")


def test_web_search_results_are_parsed_for_the_sources_tab():
    """Audit of 2026-11-01 (US-T3-1): `web_results` was never sent. The pattern must
    follow the web_search_tool._format format; this test breaks if either one changes."""
    from sensai.execution.sandbox.browser_sandbox import SearchOutcome, SearchResult
    from sensai.tools.web_search_tool import WebSearchTool
    from sensai.web.runtime import _WEB_RESULT

    text = WebSearchTool._format(SearchOutcome(ok=True, query="python", results=[
        SearchResult(title="Python 3.15.2", url="https://www.python.org/", snippet="Released"),
        SearchResult(title="PyPI", url="https://pypi.org/", snippet=""),
    ]))
    assert _WEB_RESULT.findall(text) == [("Python 3.15.2", "https://www.python.org/"),
                                         ("PyPI", "https://pypi.org/")]
