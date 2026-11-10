"""
Agent questions in the browser (X4, ADR-0046): the broker alone, then
the full flow through the real server.

The test that matters: `test_the_form_answer_goes_back_to_the_model` (criterion
"the agent resumes using the entered values", US-X4-1).
"""
import threading

from sensai.core.events import Done, Token
from sensai.tools.ask_user_tool import parse_question
from sensai.web.questions import WebQuestionBroker
from tests.web.conftest import types

FIELDS = [
    {"id": "style", "kind": "choice", "label": "Style", "options": ["pytest", "unittest"]},
    {"id": "name", "kind": "text", "label": "Name"},
]
ASK = ("call", "ask_user", {"title": "Which test style?", "fields": FIELDS})
GOOD = {"style": "pytest", "name": "test_tools"}

# --- The broker alone---------------------------------------------------------------


def _ask_in_thread(broker):
    result = {}
    thread = threading.Thread(
        target=lambda: result.setdefault("v", broker.ask(parse_question("?", FIELDS))))
    thread.start()
    return thread, result


def test_the_broker_returns_the_valid_answer():
    sent = []
    broker = WebQuestionBroker(sent.append, timeout_s=5)
    thread, result = _ask_in_thread(broker)
    while not sent:
        pass
    question_id = sent[0]["question_id"]
    assert broker.resolve(question_id, {"style": "nose", "name": "x"}) == "style: unknown choice"
    assert broker.resolve(question_id, GOOD) == "ok"
    thread.join(5)
    assert result["v"] == GOOD
    assert broker.resolve(question_id, GOOD) == "unknown"  # already answered


def test_without_a_timely_answer_the_broker_returns_none():
    broker = WebQuestionBroker(lambda e: None, timeout_s=0.2)
    assert broker.ask(parse_question("?", FIELDS)) is None


def test_a_closed_broker_asks_no_more_questions():
    sent = []
    broker = WebQuestionBroker(sent.append, timeout_s=5)
    broker.close()
    assert broker.ask(parse_question("?", FIELDS)) is None and sent == []


def test_a_broken_emit_means_no_answer():
    def broken(event):
        raise RuntimeError("stream closed")
    assert WebQuestionBroker(broken, timeout_s=5).ask(parse_question("?", FIELDS)) is None


# --- Through the server ---------------------------------------------------------------


def _answer(env, session_id, values, expect=204):
    def on_event(event):
        if event["type"] == "question":
            assert event["title"] == "Which test style?"
            assert [f["id"] for f in event["fields"]] == ["style", "name"]
            response = env.post(f"/api/sessions/{session_id}/answer",
                                {"question_id": event["question_id"], "values": values})
            assert response.status_code == expect, response.text
    return on_event


def test_the_form_answer_goes_back_to_the_model(env):
    env.script.steps = [ASK, Token("Understood."), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Write some tests", on_event=_answer(env, session_id, GOOD))
    assert types(events) == ["tool_call", "question", "tool_return", "token", "done"]
    assert events[2]["ok"] is True
    assert '"style": "pytest"' in events[2]["content"]
    assert '"name": "test_tools"' in events[2]["content"]


def test_an_invalid_answer_is_rejected_and_the_question_stays_open(env):
    env.script.steps = [ASK, Done("final_answer")]
    session_id = env.session()

    def on_event(event):
        if event["type"] == "question":
            bad = env.post(f"/api/sessions/{session_id}/answer",
                           {"question_id": event["question_id"],
                            "values": {"style": "nose", "name": "x"}})
            assert bad.status_code == 400 and bad.json()["code"] == "INVALID_ANSWER"
            good = env.post(f"/api/sessions/{session_id}/answer",
                            {"question_id": event["question_id"], "values": GOOD})
            assert good.status_code == 204

    events = env.stream(session_id, "Write some tests", on_event=on_event)
    assert events[2]["type"] == "tool_return" and events[2]["ok"] is True


def test_unknown_question(env):
    session_id = env.session()
    response = env.post(f"/api/sessions/{session_id}/answer",
                        {"question_id": "question_x", "values": {}})
    assert response.status_code == 404 and response.json()["code"] == "QUESTION_NOT_FOUND"


def test_interrupt_during_a_question(env):
    env.script.steps = [ASK, Token("Never said."), Done("final_answer")]
    session_id = env.session()

    def on_event(event):
        if event["type"] == "question":
            env.post(f"/api/sessions/{session_id}/interrupt")

    events = env.stream(session_id, "Write some tests", on_event=on_event)
    assert events[-1] == {"type": "done", "reason": "interrupted"}
    assert "Never said." not in [e.get("text") for e in events]


def test_a_secret_typed_in_the_form_is_masked_before_the_model(env):
    env.script.steps = [ASK, Done("final_answer")]
    session_id = env.session()
    secret = "AKIAIOSFODNN7EXAMPLE"
    events = env.stream(session_id, "Write some tests",
                        on_event=_answer(env, session_id, {"style": "pytest", "name": secret}))
    assert secret not in events[2]["content"]
