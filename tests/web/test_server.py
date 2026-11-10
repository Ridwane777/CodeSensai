"""
The real web server (ADR-0035): API, stream, confirmation, interruption, memory.

Each block refers to the server user stories (docs/architecture/web-api.md)
and to decisions ADR-0022 to 0024.

The tests that matter most:
- `test_only_a_timely_yes_allows_the_write` and its neighbors: a risky
  action runs only with an explicit, timely "yes" (ADR-0015).
- `test_every_route_requires_the_token`: the API never opens without a token (ADR-0023).
- `test_same_agent_as_the_cli`: the web offers the same tools as the CLI.
"""
import threading
import time

import pytest
import requests

from sensai.core.events import Done, Error, Thought, Token
from sensai.knowledge.memory import SESSIONS_FILE, SessionStore
from tests.web.conftest import TOKEN, types

# --- Access (ADR-0023) ------------------------------------------------------------

ROUTES = [
    ("get", "/api/config"),
    ("get", "/api/sessions"),
    ("post", "/api/sessions"),
    ("get", "/api/sessions/abc"),
    ("post", "/api/sessions/abc/messages"),
    ("post", "/api/sessions/abc/confirm"),
    ("post", "/api/sessions/abc/answer"),
    ("post", "/api/sessions/abc/interrupt"),
    ("post", "/api/sessions/abc/fork"),
    ("get", "/api/sessions/abc/export"),
    ("post", "/api/sessions/abc/delete"),
    ("post", "/api/sessions/abc/share"),
    ("post", "/api/shares/abc/revoke"),
    ("get", "/api/profile"),
    ("post", "/api/profile/preferences"),
    ("post", "/api/profile/forget"),
    ("get", "/api/facts"),
    ("get", "/api/fewshot"),
    ("post", "/api/facts/forget"),
    ("get", "/api/state"),
    ("get", "/api/personas"),
    ("get", "/api/sessions/abc/persona"),
    ("post", "/api/sessions/abc/persona"),
    ("get", "/api/prompts"),
    ("get", "/api/prompts/system/v1"),
    ("get", "/api/prompts/system/diff"),
    ("get", "/api/sessions/abc/prompt-trial"),
    ("post", "/api/sessions/abc/prompt-trial"),
]


def test_health_without_token(env):
    assert requests.get(f"{env.base}/api/health", timeout=5).json() == {"status": "ok"}


@pytest.mark.parametrize("method, path", ROUTES)
@pytest.mark.parametrize("header", [None, "Bearer fake", "Basic " + TOKEN, TOKEN, "Bearer "])
def test_every_route_requires_the_token(env, method, path, header):
    headers = {"Authorization": header} if header else {}
    response = getattr(requests, method)(env.base + path, headers=headers, json={}, timeout=5)
    assert response.status_code == 401
    assert response.json() == {"error": "Authentication required", "code": "UNAUTHORIZED",
                               "details": ""}


def test_the_config_reveals_neither_address_nor_path(env):
    config = env.get("/api/config").json()
    text = str(config)
    assert config["model"] == "fake-model" and config["project"] == "project"
    assert "127.0.0.1" not in text and str(env.project) not in text and TOKEN not in text


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_no_public_documentation(env, path):
    assert requests.get(env.base + path, timeout=5).status_code == 404


def test_cors_closed(env):
    def preflight(origin):
        return requests.options(f"{env.base}/api/sessions", timeout=5, headers={
            "Origin": origin, "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in preflight("http://evil.example").headers
    allowed = preflight("http://allowed.example").headers
    assert allowed["access-control-allow-origin"] == "http://allowed.example"


# --- Sessions (M1, US-WEB-6) ------------------------------------------------------------


def test_a_web_session_is_a_cli_session(env):
    session_id = env.session()
    env.stream(session_id, "Hello")
    store = SessionStore(env.runtime.data_dir / SESSIONS_FILE)
    assert store.load(session_id) == [{"role": "user", "content": "Hello"},
                                      {"role": "assistant", "content": "Hello."}]
    listed = env.get("/api/sessions").json()
    assert [s["session_id"] for s in listed] == [session_id]
    assert listed[0]["message_count"] == 2 and listed[0]["title"] == "Hello"


def test_an_empty_session_is_not_listed(env):
    env.session()
    assert env.get("/api/sessions").json() == []


def test_unknown_session(env):
    response = env.get("/api/sessions/unknown")
    assert response.status_code == 404
    assert response.json()["code"] == "SESSION_NOT_FOUND"
    assert env.post("/api/sessions/unknown/messages", {"content": "x"}).status_code == 404


def test_the_history_is_sent_to_the_model(env):
    session_id = env.session()
    env.stream(session_id, "First")
    env.stream(session_id, "Second")
    messages = env.script.calls[-1]
    assert messages[0]["role"] == "system" and "Conversation resumed." in messages[0]["content"]
    assert [m["content"] for m in messages[1:]] == ["First", "Hello.", "Second"]


# --- The stream of a turn (ADR-0022) ----------------------------------------------------


def test_the_stream_ends_with_done(env):
    env.script.steps = [Thought("Thinking."), Token("Hel"), Token("lo."),
                        Done("final_answer")]
    events = env.stream(env.session(), "Hi")
    assert types(events) == ["thought", "token", "token", "done"]
    assert events[-1] == {"type": "done", "reason": "final_answer"}


def test_read_tool_call(env):
    env.script.steps = [("call", "read_file", {"path": "notes.md"}), Token("Read."),
                        Done("final_answer")]
    events = env.stream(env.session(), "Read notes.md")
    call, result = events[0], events[1]
    assert call == {"type": "tool_call", "id": "c1", "name": "read_file",
                    "arguments": {"path": "notes.md"}}
    assert result["type"] == "tool_return" and result["ok"] and "pytest -q" in result["content"]


def test_a_model_error_does_not_enter_the_history(env):
    env.script.steps = [Error("Ollama unreachable"), Done("error")]
    session_id = env.session()
    events = env.stream(session_id, "Hello")
    assert types(events) == ["error", "done"]
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []


def test_a_core_bug_closes_the_stream_cleanly(env):
    env.script.raise_error = True
    events = env.stream(env.session(), "Hello")
    assert events == [{"type": "error", "message": "Internal server error."},
                      {"type": "done", "reason": "error"}]


@pytest.mark.parametrize("body, status, code", [
    ({"content": "   "}, 400, "EMPTY_MESSAGE"),
    ({"content": "x" * 20_001}, 413, "MESSAGE_TOO_LONG"),
    ({}, 400, "INVALID_REQUEST"),
    ({"content": 42}, 400, "INVALID_REQUEST"),
])
def test_rejected_messages(env, body, status, code):
    response = env.post(f"/api/sessions/{env.session()}/messages", body)
    assert response.status_code == status and response.json()["code"] == code


def test_invalid_json(env):
    response = requests.post(f"{env.base}/api/sessions/{env.session()}/messages",
                             data="{not json", timeout=5,
                             headers={**env.headers(), "Content-Type": "application/json"})
    assert response.status_code == 400 and response.json()["code"] == "INVALID_REQUEST"


def test_one_turn_at_a_time(env):
    env.script.pause = 0.3
    session_id = env.session()
    started = threading.Event()
    statuses = []

    def second(event):
        if not started.is_set():
            started.set()
            statuses.append(env.post(f"/api/sessions/{session_id}/messages",
                                     {"content": "again"}).status_code)

    env.stream(session_id, "Hello", on_event=second)
    assert statuses == [409]
    assert types(env.stream(session_id, "Next"))[-1] == "done", "the session is released"


def test_two_sessions_in_parallel(env):
    env.script.pause = 0.1
    a, b = env.session(), env.session()
    results = {}
    threads = [threading.Thread(target=lambda s=s: results.__setitem__(s, env.stream(s, s)))
               for s in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for s in (a, b):
        assert types(results[s])[-1] == "done"
        assert env.get(f"/api/sessions/{s}").json()["messages"][0]["content"] == s


# --- Confirmation (A3, ADR-0015) --------------------------------------------------------

WRITE = ("call", "write_file", {"path": "new.txt", "content": "hi\n"})


def answer(env, session_id, approved):
    def on_event(event):
        if event["type"] == "confirm_request":
            assert event["confirm_id"] == event["id"] and event["tool"] == "write_file"
            assert event["risk"] == "write" and event["arguments"]["path"] == "new.txt"
            assert "new.txt" in event["summary"]
            status = env.post(f"/api/sessions/{session_id}/confirm",
                              {"confirm_id": event["confirm_id"], "approved": approved})
            assert status.status_code == 204
    return on_event


def test_only_a_timely_yes_allows_the_write(env):
    env.script.steps = [WRITE, Token("Written."), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Write", on_event=answer(env, session_id, True))
    assert types(events) == ["tool_call", "confirm_request", "tool_return", "token", "done"]
    assert events[2]["ok"] is True
    assert (env.project / "new.txt").read_text() == "hi\n"


def test_no_refuses_the_write(env):
    env.script.steps = [WRITE, Token("Refused."), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Write", on_event=answer(env, session_id, False))
    assert events[2]["type"] == "tool_return" and events[2]["ok"] is False
    assert not (env.project / "new.txt").exists()


@pytest.mark.parametrize("value", ["true", 1, "yes"])
def test_only_boolean_true_counts(env, value):
    env.script.steps = [WRITE, Done("final_answer")]
    session_id = env.session()

    def on_event(event):
        if event["type"] == "confirm_request":
            response = env.post(f"/api/sessions/{session_id}/confirm",
                                {"confirm_id": event["confirm_id"], "approved": value})
            # pydantic would accept "true", 1 or "yes" as true: only the JSON
            # boolean true must count, anything else is rejected on input.
            assert response.status_code == 400
            env.post(f"/api/sessions/{session_id}/confirm",
                     {"confirm_id": event["confirm_id"], "approved": False})

    env.stream(session_id, "Write", on_event=on_event)
    assert not (env.project / "new.txt").exists()


def test_no_timely_answer_means_refusal(make_env):
    env = make_env(confirm_timeout_s=0.5)
    env.script.steps = [WRITE, Done("final_answer")]
    session_id = env.session()
    seen = []

    def late(event):
        if event["type"] == "confirm_request":
            seen.append(event["confirm_id"])
        if event["type"] == "tool_return":
            response = env.post(f"/api/sessions/{session_id}/confirm",
                                {"confirm_id": seen[0], "approved": True})
            assert response.status_code == 404, "a late answer has no effect"

    events = env.stream(session_id, "Write", on_event=late)
    assert next(e for e in events if e["type"] == "tool_return")["ok"] is False
    assert not (env.project / "new.txt").exists()


def test_unknown_or_already_given_confirmation(env):
    env.script.steps = [WRITE, Done("final_answer")]
    session_id = env.session()
    assert env.post(f"/api/sessions/{session_id}/confirm",
                    {"confirm_id": "unknown", "approved": True}).status_code == 404
    codes = []

    def twice(event):
        if event["type"] == "confirm_request":
            for approved in (False, True):
                codes.append(env.post(f"/api/sessions/{session_id}/confirm",
                                      {"confirm_id": event["confirm_id"],
                                       "approved": approved}).status_code)

    env.stream(session_id, "Write", on_event=twice)
    assert codes == [204, 404], "the first answer wins"
    assert not (env.project / "new.txt").exists()


# --- Interruption and disconnection (X2, US-WEB-7)-------------------------------------


def test_interrupt_during_a_confirmation(env):
    env.script.steps = [WRITE, Token("after"), Done("final_answer")]
    session_id = env.session()

    def stop(event):
        if event["type"] == "confirm_request":
            assert env.post(f"/api/sessions/{session_id}/interrupt").status_code == 204

    events = env.stream(session_id, "Write", on_event=stop)
    assert events[-1] == {"type": "done", "reason": "interrupted"}
    assert "token" not in types(events)
    assert not (env.project / "new.txt").exists()
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []


def test_interrupt_without_a_turn_has_no_effect(env):
    assert env.post(f"/api/sessions/{env.session()}/interrupt").status_code == 204


def test_tab_closed_during_a_confirmation(env):
    env.script.steps = [WRITE, Done("final_answer")]
    session_id = env.session()
    with requests.post(f"{env.base}/api/sessions/{session_id}/messages",
                       json={"content": "Write"}, headers=env.headers(), stream=True,
                       timeout=10) as response:
        for line in response.iter_lines(decode_unicode=True):
            if line and "confirm_request" in line:
                break  # close without answering
    for _ in range(100):  # the session is released: a new message is accepted
        env.script.steps = [Token("ok"), Done("final_answer")]
        reply = env.post(f"/api/sessions/{session_id}/messages", {"content": "again"})
        if reply.status_code == 200:
            break
        time.sleep(0.05)
    assert reply.status_code == 200
    assert not (env.project / "new.txt").exists()


# --- Guardrails, commands, cache, RAG ----------------------------------------------------


def test_a_blocked_input_is_not_sent_to_the_model(make_env):
    env = make_env(blocklist=[{"name": "forbidden", "pattern": "forbidden-word",
                               "why": "refused topic"}])
    session_id = env.session()
    events = env.stream(session_id, "talk about the forbidden-word")
    assert types(events) == ["guardrail", "done"]
    assert events[0]["kind"] == "unsafe" and events[1]["reason"] == "blocked"
    assert env.script.calls == []
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []


def test_chat_commands_work_like_in_the_cli(env):
    session_id = env.session()
    events = env.stream(session_id, "/state")
    assert types(events) == ["token", "done"] and events[1]["reason"] == "command"
    terminal = env.stream(session_id, "/schedule list")
    assert "terminal" in terminal[0]["text"]
    env.stream(session_id, "/remember answer in French")
    assert "answer in French" in env.get("/api/profile").json()["preferences"]
    assert env.script.calls == []
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []


def test_the_cache_answers_without_calling_the_model_again(make_env):
    env = make_env(cache=True)
    session_id = env.session()
    question = "How do I run the project tests?"
    env.stream(session_id, question)
    events = env.stream(session_id, question)
    assert types(events) == ["cache_hit", "token", "done"]
    assert events[0]["question"] == question and events[0]["similarity"] >= 0.99
    assert events[1]["text"] == "Hello."
    assert len(env.script.calls) == 1
    env.stream(session_id, question, skip_cache=True)
    assert len(env.script.calls) == 2, "/again asks the model again"


def test_an_answer_that_listed_files_is_cached(make_env):
    """Demo rehearsal of 2026-11-06: list_files (ADR-0059) only reads, but since it
    was not among the "cacheable" tools, the answer was never kept."""
    env = make_env(cache=True)
    env.script.steps = [("call", "list_files", {}), Token("pytest -q"), Done("final_answer")]
    session_id = env.session()
    question = "How do I run the project tests?"
    env.stream(session_id, question)
    events = env.stream(env.session(), question)
    assert types(events)[0] == "cache_hit"
    assert len(env.script.calls) == 1


def test_rag_sources_are_sent(make_env):
    env = make_env(rag=True)
    events = env.stream(env.session(), "How do I run the tests?")
    sources = next(e for e in events if e["type"] == "rag_sources")["sources"]
    assert sources[0]["path"] == "notes.md" and sources[0]["lines"] == "1-2"
    assert "notes.md" in env.script.calls[0][-1]["content"], "the passages are sent to the model"


# --- Fork, export, memory --------------------------------------------------------------


def test_fork(env):
    session_id = env.session()
    env.stream(session_id, "First")
    env.stream(session_id, "Second")
    branch = env.post(f"/api/sessions/{session_id}/fork", {"at_message": 2})
    assert branch.status_code == 201
    new_id = branch.json()["session_id"]
    assert new_id != session_id
    assert [m["content"] for m in env.get(f"/api/sessions/{new_id}").json()["messages"]] == [
        "First", "Hello."]
    assert env.post(f"/api/sessions/{session_id}/fork", {"at_message": 9}).status_code == 400
    assert env.post(f"/api/sessions/{session_id}/fork", {"at_message": -1}).status_code == 400


def test_delete_a_conversation(env):
    session_id = env.session()
    env.stream(session_id, "Hello")
    assert env.post(f"/api/sessions/{session_id}/delete").status_code == 204
    assert env.get(f"/api/sessions/{session_id}").status_code == 404
    assert session_id not in [s["session_id"] for s in env.get("/api/sessions").json()]
    assert env.post(f"/api/sessions/{session_id}/delete").status_code == 404


def test_no_deletion_during_a_turn(env):
    env.script.pause = 0.3
    session_id = env.session()
    codes = []

    def on_event(event):
        if not codes:
            codes.append(env.post(f"/api/sessions/{session_id}/delete").status_code)

    env.stream(session_id, "Hello", on_event=on_event)
    assert codes == [409]
    assert env.get(f"/api/sessions/{session_id}").status_code == 200


def test_export_filters_secrets(env):
    session_id = env.session()
    env.script.steps = [Token("Your key: sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"),
                        Done("final_answer")]
    env.stream(session_id, "password = hunter2-very-secret")
    as_json = env.get(f"/api/sessions/{session_id}/export?format=json")
    text = str(as_json.json())
    assert "hunter2-very-secret" not in text and "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in text
    assert "REDACTED" in text
    as_md = env.get(f"/api/sessions/{session_id}/export?format=md")
    assert as_md.headers["content-type"].startswith("text/markdown")
    assert "## You" in as_md.text and "hunter2-very-secret" not in as_md.text
    assert env.get(f"/api/sessions/{session_id}/export?format=pdf").status_code == 400


def test_preferences_added_then_forgotten_from_the_web(env):
    """US-WEB-6: add (empty or duplicate ignored), clear; the profile file follows,
    and the preference enters the next turn's prompt."""
    add = lambda text: env.post("/api/profile/preferences", {"text": text})  # noqa: E731
    assert add("use pytest").json()["preferences"] == ["use pytest"]
    assert add("use pytest").json()["preferences"] == ["use pytest"]
    assert add("   ").json()["preferences"] == ["use pytest"]
    assert "use pytest" in env.runtime.profile_path.read_text(encoding="utf-8")
    env.stream(env.session(), "Hello")
    assert "use pytest" in env.script.calls[-1][0]["content"]
    assert env.post("/api/profile/forget").json()["preferences"] == []
    assert env.get("/api/profile").json()["preferences"] == []


def test_a_too_long_preference_is_rejected(env):
    response = env.post("/api/profile/preferences", {"text": "x" * 501})
    assert response.status_code == 400 and response.json()["code"] == "INVALID_REQUEST"


def test_forget_the_facts_of_an_entity(env):
    """Trial run of 2026-11-01: facts survive the deletion of a conversation;
    the web must be able to forget them."""
    env.runtime.facts.remember("test_word", "word", "purple-zebra")
    assert "test_word" in env.get("/api/facts").json()["facts"]
    assert env.post("/api/facts/forget", {"entity": "test_word"}).json() == {"removed": 1}
    assert "test_word" not in env.get("/api/facts").json()["facts"]
    assert env.post("/api/facts/forget", {"entity": "test_word"}).status_code == 404


def test_facts_and_state_document(env):
    env.runtime.facts.remember("redis", "version", "8")
    assert env.get("/api/facts").json()["facts"]["redis"][0]["value"] == "8"
    state = env.get("/api/state").json()
    assert state["markdown"] == "" and "Done" in state["sections"]


# --- The served UI, parity with the CLI, purge (#65) ----------------------------------


def test_the_ui_is_served_with_the_api(make_env, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>CodeSensai</html>", encoding="utf-8")
    env = make_env(frontend_dir=dist)
    assert "CodeSensai" in requests.get(env.base + "/", timeout=5).text
    assert env.get("/api/config").status_code == 200


def test_without_a_built_ui_the_api_works_alone(env):
    assert requests.get(env.base + "/", timeout=5).status_code == 404
    assert env.get("/api/config").status_code == 200


def test_same_agent_as_the_cli(env):
    from sensai.registry import build_registry
    from sensai.tools.ask_user_tool import AskUserTool
    from sensai.tools.delegate_tool import DelegateTool
    from sensai.tools.fact_tools import RecallFactsTool, RememberFactTool
    from sensai.tools.rag_tool import RagTool
    from sensai.tools.schedule_task_tool import ScheduleTaskTool
    from sensai.tools.state_tool import UpdateStateTool
    from sensai.tools.team_tool import TeamTool

    cli = build_registry(env.settings["file_permissions"])
    for tool in (RagTool(), UpdateStateTool(env.runtime.state),
                 RememberFactTool(env.runtime.facts), RecallFactsTool(env.runtime.facts),
                 DelegateTool("h", "m", tools=None),
                 TeamTool(DelegateTool("h", "m", tools=None)), AskUserTool(None),
                 ScheduleTaskTool(env.runtime.data_dir)):
        cli.register(tool)
    env.runtime.rag_on = True
    web = env.runtime.make_gateway(lambda request: False)
    assert sorted(t["name"] for t in web.describe_all()) == sorted(
        t["name"] for t in cli.describe_all())


def test_old_sessions_are_purged_at_startup(env):
    import sqlite3
    old = env.runtime.store.create(env.runtime.project)
    env.runtime.store.save(old, [{"role": "user", "content": "old"}])
    with sqlite3.connect(env.runtime.store.db_path) as conn:
        conn.execute("UPDATE sessions SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                     (old,))
    assert env.runtime.purge() == 1
    assert not env.runtime.store.exists(old)


def test_rag_passages_are_filtered(make_env):
    """EV2, like the CLI: no plaintext secret in the passages added to the question."""
    env = make_env(rag=True)
    (env.project / "settings_file.py").write_text(
        '# how to run the tests\nAPI_KEY = "sk-abcdef1234567890abcdef"\n', encoding="utf-8")
    env.stream(env.session(), "How do I run the tests?")
    sent = env.script.calls[0][-1]["content"]
    assert "settings_file.py" in sent
    assert "sk-abcdef1234567890abcdef" not in sent


def test_context_shows_the_exact_prompt_without_calling_the_model(env):
    """ADR-0058: `/context` in the web chat, without a model turn or saving."""
    session_id = env.session()
    events = env.stream(session_id, "/context")
    assert types(events) == ["token", "done"] and events[1]["reason"] == "command"
    assert "--- [1] system" in events[0]["text"] and "num_ctx=" in events[0]["text"]
    assert env.script.calls == []
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []
