"""
[Workstream A] Personas (A5) and prompt versions (A4) in the web UI:
ADR-0054 and ADR-0055.

- The persona is chosen per conversation, in server memory (like the CLI):
  system prompt, disabled tools (subagent included) and cache bypassed.
- The prompt registry is read, never written: a version trial applies only
  to one conversation.
"""
import threading
import time

import pytest

from sensai.core.events import Done, Token
from sensai.knowledge.persona import PersonaStore
from sensai.knowledge.prompt_versions import PromptStore
from tests.web.conftest import types

PERSONAS = {
    "default": "assistant",
    "profiles": [
        {"id": "assistant", "name": "CodeSensai", "role": "development assistant",
         "tone": "neutral", "scope": "the project"},
        {"id": "reviewer", "name": "Reviewer", "role": "code reviewer",
         "tone": "direct", "scope": "code review", "tools": {"disabled": ["write_file"]}},
    ],
}


@pytest.fixture
def penv(make_env):
    return make_env(personas=PersonaStore.from_config(PERSONAS))


def prompt_store(root):
    store = PromptStore(root / "prompts")
    store.save("system", "System prompt v1.", "first", "Fresnel", date="2026-10-01")
    store.save("system", "System prompt v2.", "second", "Fresnel", date="2026-10-10")
    store.save("memory", "Resumed.", "memory", "Fresnel", date="2026-10-01")
    return store


@pytest.fixture
def prenv(make_env, tmp_path):
    store = prompt_store(tmp_path)
    store.use("system", "v1")
    return make_env(prompt_store=store)


# --- Personas (A5) ---------------------------------------------------------------------


def test_persona_list(penv):
    personas = penv.get("/api/personas").json()
    assert [p["id"] for p in personas] == ["assistant", "reviewer"]
    assert personas[0]["default"] is True and personas[1]["default"] is False
    assert personas[1]["tools_disabled"] == ["write_file"]
    assert personas[1]["role"] == "code reviewer"


def test_default_is_the_configured_persona(penv):
    session_id = penv.session()
    assert penv.get(f"/api/sessions/{session_id}/persona").json()["id"] == "assistant"


def test_changing_persona_changes_the_turn_prompt(penv):
    session_id = penv.session()
    response = penv.post(f"/api/sessions/{session_id}/persona", {"persona": "reviewer"})
    assert response.status_code == 200 and response.json()["id"] == "reviewer"
    assert penv.get(f"/api/sessions/{session_id}/persona").json()["id"] == "reviewer"
    penv.stream(session_id, "Hello")
    system = penv.script.calls[-1][0]["content"]
    assert penv.runtime.personas.get("reviewer").as_prompt() in system
    # Another conversation keeps the default persona.
    other = penv.session()
    penv.stream(other, "Hello")
    assert "You are CodeSensai" in penv.script.calls[-1][0]["content"]


def test_unknown_persona(penv):
    session_id = penv.session()
    response = penv.post(f"/api/sessions/{session_id}/persona", {"persona": "pirate"})
    assert response.status_code == 404 and response.json()["code"] == "PERSONA_NOT_FOUND"
    assert penv.post("/api/sessions/unknown/persona",
                     {"persona": "reviewer"}).status_code == 404


def _during_turn(env, session_id, action):
    """Start a slow turn and call `action` while it runs."""
    env.script.pause = 0.3
    env.script.steps = [Token("a"), Token("b"), Done("final_answer")]
    thread = threading.Thread(target=env.stream, args=(session_id, "Long"))
    thread.start()
    time.sleep(0.15)
    try:
        return action()
    finally:
        thread.join(timeout=10)


def test_no_persona_change_during_a_turn(penv):
    session_id = penv.session()
    response = _during_turn(penv, session_id, lambda: penv.post(
        f"/api/sessions/{session_id}/persona", {"persona": "reviewer"}))
    assert response.status_code == 409
    assert penv.get(f"/api/sessions/{session_id}/persona").json()["id"] == "assistant"


def test_the_persona_removes_write_file_from_the_main_agent(penv):
    session_id = penv.session()
    penv.post(f"/api/sessions/{session_id}/persona", {"persona": "reviewer"})
    gateway = penv.runtime.make_gateway(lambda r: False,
                                        persona=penv.runtime.persona_of(session_id))
    assert "write_file" not in {t["name"] for t in gateway.describe_all()}
    penv.script.steps = [("call", "write_file", {"path": "x.txt", "content": "x"}),
                         Done("final_answer")]
    events = penv.stream(session_id, "Write x.txt")
    returned = [e for e in events if e["type"] == "tool_return"]
    assert returned and returned[0]["ok"] is False
    assert "confirm_request" not in types(events)
    assert not (penv.project / "x.txt").exists()
    # The default persona keeps write_file.
    default = penv.runtime.make_gateway(lambda r: False)
    assert "write_file" in {t["name"] for t in default.describe_all()}


def test_the_persona_applies_to_the_subagent(penv, monkeypatch):
    seen = {}

    def fake_subagent(host, model, messages, tools, **kw):
        seen["system"] = messages[0]["content"]
        seen["offered"] = {t["name"] for t in tools.describe_all()}
        seen["result"] = tools.call("write_file", path="y.txt", content="y")
        yield Token("done")
        yield Done("final_answer")

    monkeypatch.setattr("sensai.tools.delegate_tool._run_agent_turn", fake_subagent)
    session_id = penv.session()
    penv.post(f"/api/sessions/{session_id}/persona", {"persona": "reviewer"})
    penv.script.steps = [("call", "delegate_task", {"task": "write y.txt"}),
                         Done("final_answer")]

    def approve(event):
        if event["type"] == "confirm_request":
            penv.post(f"/api/sessions/{session_id}/confirm",
                      {"confirm_id": event["confirm_id"], "approved": True})

    penv.stream(session_id, "Delegate", approve)
    assert "write_file" not in seen["offered"]
    assert seen["result"].ok is False
    assert penv.runtime.personas.get("reviewer").as_prompt() in seen["system"]
    assert not (penv.project / "y.txt").exists()


def test_a_restrictive_persona_neither_reads_nor_writes_the_cache(make_env):
    env = make_env(cache=True, personas=PersonaStore.from_config(PERSONAS))
    session_id = env.session()
    env.post(f"/api/sessions/{session_id}/persona", {"persona": "reviewer"})
    env.stream(session_id, "How do I run the tests?")
    env.stream(session_id, "How do I run the tests?")
    assert len(env.script.calls) == 2, "no answer served from the cache"
    other = env.session()
    events = env.stream(other, "How do I run the tests?")
    assert "cache_hit" not in types(events), "nothing was stored under the restrictive persona"


def test_deleting_the_conversation_forgets_its_persona(penv):
    session_id = penv.session()
    penv.post(f"/api/sessions/{session_id}/persona", {"persona": "reviewer"})
    penv.post(f"/api/sessions/{session_id}/delete")
    assert penv.runtime.persona_of(session_id).id == "assistant"


# --- Prompt versions (A4) -------------------------------------------------------------


def test_registry_list(prenv):
    prompts = {p["name"]: p for p in prenv.get("/api/prompts").json()}
    assert set(prompts) == {"system", "memory"}
    system = prompts["system"]
    assert system["active"] == "v1"
    assert [v["id"] for v in system["versions"]] == ["v2", "v1"]
    assert system["versions"][1] == {"id": "v1", "date": "2026-10-01", "author": "Fresnel",
                                     "description": "first", "active": True}


def test_text_and_diff_of_a_version(prenv):
    text = prenv.get("/api/prompts/system/v2").json()
    assert text == {"name": "system", "version": "v2", "text": "System prompt v2."}
    diff = prenv.get("/api/prompts/system/diff", params={"a": "v1", "b": "v2"}).json()
    assert "-System prompt v1." in diff["diff"] and "+System prompt v2." in diff["diff"]
    assert prenv.get("/api/prompts/system/v9").status_code == 404
    assert prenv.get("/api/prompts/unknown/v1").status_code == 404
    assert prenv.get("/api/prompts/system/diff", params={"a": "v1", "b": "v9"}).status_code == 404


def test_trying_a_version_in_one_conversation(prenv):
    session_id = prenv.session()
    response = prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": "v2"})
    assert response.json() == {"prompt": "system", "active": "v1", "trial": "v2"}
    prenv.stream(session_id, "Hello")
    system = prenv.script.calls[-1][0]["content"]
    assert system.startswith("System prompt v2.") and "You are CodeSensai." not in system
    # Another conversation keeps the prompt loaded at startup.
    other = prenv.session()
    prenv.stream(other, "Hello")
    assert prenv.script.calls[-1][0]["content"].startswith("You are CodeSensai.")
    # Back to the active version.
    back = prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": None}).json()
    assert back["trial"] is None
    prenv.stream(session_id, "Again")
    assert prenv.script.calls[-1][0]["content"].startswith("You are CodeSensai.")


def test_trial_of_unknown_version_or_during_a_turn(prenv):
    session_id = prenv.session()
    response = prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": "v9"})
    assert response.status_code == 404 and response.json()["code"] == "PROMPT_VERSION_NOT_FOUND"
    busy = _during_turn(prenv, session_id, lambda: prenv.post(
        f"/api/sessions/{session_id}/prompt-trial", {"version": "v2"}))
    assert busy.status_code == 409
    assert prenv.get(f"/api/sessions/{session_id}/prompt-trial").json()["trial"] is None


def test_the_web_never_writes_the_registry(prenv):
    store = prenv.runtime.prompt_store
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    session_id = prenv.session()
    prenv.get("/api/prompts")
    prenv.get("/api/prompts/system/v2")
    prenv.get("/api/prompts/system/diff", params={"a": "v1", "b": "v2"})
    prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": "v2"})
    prenv.stream(session_id, "Hello")
    prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": None})
    after = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert after == before


def test_a_trial_bypasses_the_cache(make_env, tmp_path):
    env = make_env(cache=True, prompt_store=prompt_store(tmp_path))
    session_id = env.session()
    env.stream(session_id, "How do I run the tests?")
    trial = env.session()
    env.post(f"/api/sessions/{trial}/prompt-trial", {"version": "v1"})
    events = env.stream(trial, "How do I run the tests?")
    assert "cache_hit" not in types(events)
    assert len(env.script.calls) == 2
