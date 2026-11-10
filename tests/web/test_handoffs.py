"""
Handoffs between agents in the web UI (X1, A2): the server publishes a real
`agent_handoff` when a subagent takes over, and when the main agent takes back control.

Subagents really run, against an unreachable Ollama: they fail fast,
which is enough to check WHO had control and in which order.
"""
from sensai.core.events import Done
from tests.web.conftest import types

DELEGATE = ("call", "delegate_task", {"task": "Read the module", "role": "explorateur"})
TEAM = ("call", "team_task", {"task": "Fix the bug"})


def _confirm(env, session_id, approved=True):
    def on_event(event):
        if event["type"] == "confirm_request":
            env.post(f"/api/sessions/{session_id}/confirm",
                     {"confirm_id": event["confirm_id"], "approved": approved})
    return on_event


def _handoffs(events):
    return [(e["from"], e["to"]) for e in events if e["type"] == "agent_handoff"]


def test_a_delegation_announces_the_handoff_and_the_return(env):
    env.script.steps = [DELEGATE, Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Delegate", on_event=_confirm(env, session_id))
    assert _handoffs(events) == [("main", "explorateur"), ("explorateur", "main")]
    # The handoff follows the confirmation and precedes the tool result.
    order = types(events)
    assert order.index("confirm_request") < order.index("agent_handoff")
    assert max(i for i, t in enumerate(order) if t == "agent_handoff") < order.index("tool_return")


def test_a_refused_delegation_announces_no_handoff(env):
    env.script.steps = [DELEGATE, Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Delegate", on_event=_confirm(env, session_id, False))
    assert _handoffs(events) == []


def test_without_a_role_it_is_a_subagent(env):
    env.script.steps = [("call", "delegate_task", {"task": "Summarize"}), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Delegate", on_event=_confirm(env, session_id))
    assert _handoffs(events) == [("main", "sous-agent"), ("sous-agent", "main")]


def test_the_team_announces_each_handoff_then_the_return(env):
    env.script.steps = [TEAM, Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Team", on_event=_confirm(env, session_id))
    assert _handoffs(events) == [
        ("main", "explorateur"),
        ("explorateur", "developpeur"),
        ("developpeur", "relecteur"),
        ("relecteur", "main"),
    ]
