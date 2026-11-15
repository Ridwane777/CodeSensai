"""Tests the `delegate_task` tool - feature [A2], ADR-0037.

`run_turn` is replaced by a fake turn (no Ollama): each test checks a single
DelegateTool behavior; the real ReAct loop is already tested by
tests/core/test_agent.py.
"""
import itertools

from sensai.core.events import Done, Error, Token
from sensai.core.tools import ToolResult
from sensai.execution.tool_policy import Risk, risk_of
from sensai.tools import delegate_tool
from sensai.tools.delegate_tool import MAX_DELEGATION_DEPTH, ROLES, DelegateTool, _depth


def fake_turn(events):
    def run_turn(host, model, messages, tools):
        run_turn.calls.append(
            {"host": host, "model": model, "messages": list(messages), "tools": tools}
        )
        yield from events
    run_turn.calls = []
    return run_turn


def test_declares_execute_risk():
    assert risk_of(DelegateTool("h", "m", tools=object())) is Risk.EXECUTE


def test_returns_the_sub_agent_answer():
    run_turn = fake_turn([Token(text="res"), Token(text="ult"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="do X")

    assert result.ok
    assert result.content == "result"


def test_the_task_becomes_the_only_user_message():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    outil.run(task="analyze this file")

    assert run_turn.calls[0]["messages"] == [{"role": "user", "content": "analyze this file"}]


def test_the_persona_goes_into_the_system_message():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    outil.run(task="analyze this file", persona="security reviewer")

    messages = run_turn.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "security reviewer"}
    assert messages[1] == {"role": "user", "content": "analyze this file"}


def test_the_sub_agent_goes_through_the_same_gateway():
    class Gateway:
        def __init__(self):
            self.calls = []

        def describe_all(self):
            return [{"name": "read_file"}]

        def call(self, name, /, **kwargs):
            self.calls.append((name, kwargs))
            return ToolResult(ok=True, content="read")

    def sub_agent(host, model, messages, tools):
        assert tools.describe_all() == [{"name": "read_file"}]
        yield Token(text=tools.call("read_file", path="a.py").content)
        yield Done()

    gateway = Gateway()
    result = DelegateTool("http://h", "m1", tools=gateway, run_turn=sub_agent).run(task="do X")

    assert gateway.calls == [("read_file", {"path": "a.py"})]
    assert result.content == "read"


def test_empty_task_is_rejected_without_calling_the_sub_agent():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="   ")

    assert not result.ok
    assert run_turn.calls == []


def test_sub_agent_error_is_reported_without_raising():
    run_turn = fake_turn([Error(message="Ollama down"), Done(reason="error")])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="do X")

    assert not result.ok
    assert "Ollama down" in result.content


def test_max_iterations_is_reported_but_content_is_kept():
    run_turn = fake_turn([Token(text="partial answer"), Done(reason="max_iterations")])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="do X")

    assert result.ok
    assert "partial answer" in result.content
    assert "iterations" in result.content


def test_no_answer_is_a_failure():
    run_turn = fake_turn([Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="do X")

    assert not result.ok


def test_delegation_depth_is_bounded():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)
    token = _depth.set(MAX_DELEGATION_DEPTH)

    try:
        result = outil.run(task="do X")
    finally:
        _depth.reset(token)

    assert not result.ok
    assert "Delegation depth" in result.content
    assert run_turn.calls == []


def test_depth_is_reset_after_the_call():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    outil.run(task="do X")

    assert _depth.get() == 0


def test_depth_is_bounded_through_the_real_gateway():
    """The gateway runs each tool in a thread: the depth must follow it there,
    otherwise a sub-agent that re-delegates endlessly is never stopped."""
    from sensai.core.tools import ToolRegistry
    from sensai.execution.gateway import ToolGateway

    launched = []

    def sub_agent(host, model, messages, tools):
        launched.append(messages[-1]["content"])
        if len(launched) > MAX_DELEGATION_DEPTH + 3:  # test safety net: never reached
            yield Token(text="loop")
            yield Done()
            return
        # The real gateway, not the sub-agent filtered one: the depth guardrail
        # remains the last line of defense if the filter were bypassed.
        result = gateway.call("delegate_task", task="do the same thing again")
        yield Token(text=result.content)
        yield Done()

    registry = ToolRegistry()
    gateway = ToolGateway(registry, None, confirm=lambda request: True)
    registry.register(DelegateTool("h", "m", gateway, run_turn=sub_agent))

    result = gateway.call("delegate_task", task="initial task")

    assert len(launched) == MAX_DELEGATION_DEPTH
    assert "Delegation depth exceeded" in result.content


def test_the_project_prompt_precedes_the_persona():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("h", "m", tools="gateway", run_turn=run_turn,
                         system_prompt=lambda: "Project prompt")

    outil.run(task="analyze", persona="reviewer")

    system = run_turn.calls[0]["messages"][0]
    assert system["role"] == "system"
    assert system["content"].startswith("Project prompt")
    assert "reviewer" in system["content"]


def test_the_project_prompt_is_reread_on_each_delegation():
    run_turn = fake_turn([Token(text="ok"), Done()])
    prompts = iter(["v1", "v2"])
    outil = DelegateTool("h", "m", tools="gateway", run_turn=run_turn,
                         system_prompt=lambda: next(prompts))

    outil.run(task="a")
    outil.run(task="b")

    assert [c["messages"][0]["content"] for c in run_turn.calls] == ["v1", "v2"]


def test_a_sub_agent_does_not_redelegate():
    assert MAX_DELEGATION_DEPTH == 1


def fake_clock(monkeypatch, times):
    clock = itertools.chain(times, itertools.repeat(times[-1]))
    monkeypatch.setattr(delegate_tool.time, "monotonic", lambda: next(clock))


def test_after_the_deadline_the_sub_agent_is_stopped_with_its_partial_answer(monkeypatch):
    closed = []

    def sub_agent(host, model, messages, tools):
        try:
            yield Token(text="start")
            yield Token(text=" never read")
        finally:
            closed.append(True)

    # start at 0; the first chunk arrives after the deadline (110 - 5 s)
    fake_clock(monkeypatch, [0.0, 200.0])
    result = DelegateTool("h", "m", tools="gateway", run_turn=sub_agent).run(task="long")

    assert not result.ok
    assert "deadline" in result.content
    assert "start" in result.content and "never read" not in result.content
    assert closed == [True]  # the generator is closed: nothing left in the background


def test_after_the_deadline_no_tool_and_no_confirmation(monkeypatch):
    class Gateway:
        def __init__(self):
            self.calls = []

        def describe_all(self):
            return []

        def call(self, name, /, **kwargs):
            self.calls.append(name)
            return ToolResult(ok=True, content="written")

    seen = []

    def sub_agent(host, model, messages, tools):
        seen.append(tools.call("write_file", path="x", content="y"))
        yield Token(text="done")
        yield Done()

    # start at 0, the tool call arrives at 200 s, after the deadline
    fake_clock(monkeypatch, [0.0, 200.0])
    gateway = Gateway()
    DelegateTool("h", "m", tools=gateway, run_turn=sub_agent).run(task="write")

    assert gateway.calls == []
    assert not seen[0].ok and "not run" in seen[0].content


def test_the_timeout_fits_within_the_gateway_timeout():
    from sensai.execution.tool_policy import ToolPreferences

    assert DelegateTool.timeout_s <= ToolPreferences().tool_timeout_s
    assert delegate_tool.STOP_MARGIN_S < DelegateTool.timeout_s


def test_delegate_task_is_not_offered_to_the_sub_agent():
    class Gateway:
        def describe_all(self):
            return [{"name": "read_file"}, {"name": "delegate_task"}]

    seen = []

    def sub_agent(host, model, messages, tools):
        seen.extend(d["name"] for d in tools.describe_all())
        yield Token(text="ok")
        yield Done()

    DelegateTool("h", "m", tools=Gateway(), run_turn=sub_agent).run(task="x")

    assert seen == ["read_file"]


class _Gateway:
    """Fake gateway offering every project tool and recording calls."""

    names = ("read_file", "search_codebase", "recall_facts", "write_file", "run_code",
             "web_search", "delegate_task", "team_task")

    def __init__(self):
        self.calls = []

    def describe_all(self):
        return [{"name": n} for n in self.names]

    def call(self, name, /, **kwargs):
        self.calls.append(name)
        return ToolResult(ok=True, content="done")


def _seen_tools(role):
    seen = []

    def sub_agent(host, model, messages, tools):
        seen.extend(d["name"] for d in tools.describe_all())
        seen.append(("system", messages[0]["content"]))
        yield Token(text="ok")
        yield Done()

    DelegateTool("h", "m", tools=_Gateway(), run_turn=sub_agent).run(task="x", role=role)
    return seen


def test_explorer_and_reviewer_see_no_write_tool():
    for role in ("explorateur", "relecteur"):
        names = [s for s in _seen_tools(role) if isinstance(s, str)]
        assert "read_file" in names
        assert not {"write_file", "run_code", "delegate_task", "team_task"} & set(names)


def test_developer_can_write_but_not_delegate():
    names = [s for s in _seen_tools("developpeur") if isinstance(s, str)]
    assert {"write_file", "run_code", "read_file"} <= set(names)
    assert not {"delegate_task", "team_task"} & set(names)


def test_the_role_gives_its_instructions_to_the_sub_agent():
    system = dict(s for s in _seen_tools("relecteur") if isinstance(s, tuple))["system"]
    assert system == ROLES["relecteur"].prompt


def test_a_tool_outside_the_role_is_refused_without_running():
    gateway = _Gateway()
    seen = []

    def sub_agent(host, model, messages, tools):
        seen.append(tools.call("write_file", path="a", content="b"))
        yield Token(text="ok")
        yield Done()

    DelegateTool("h", "m", tools=gateway, run_turn=sub_agent).run(task="x", role="explorateur")

    assert gateway.calls == []
    assert not seen[0].ok and "not allowed" in seen[0].content


def test_an_unknown_role_is_rejected():
    result = DelegateTool("h", "m", tools=_Gateway(), run_turn=fake_turn([])).run(
        task="x", role="pirate")
    assert not result.ok and "Unknown role" in result.content


def test_a_sub_agent_trying_to_delegate_gets_an_explicit_refusal():
    seen = []

    def sub_agent(host, model, messages, tools):
        seen.append(tools.call("team_task", task="x"))
        yield Token(text="ok")
        yield Done()

    DelegateTool("h", "m", tools=_Gateway(), run_turn=sub_agent).run(task="x")

    assert not seen[0].ok and "does not re-delegate" in seen[0].content


def test_reading_roles_see_the_project_files():
    """Trial run of 2026-11-06: without RAG, the explorer without list_files could
    not find stats.py and the developer created a new moyenne.py (ADR-0059)."""
    from sensai.tools.delegate_tool import ROLES

    for role in ("explorateur", "developpeur", "relecteur"):
        assert "list_files" in ROLES[role].tools, role
    assert "write_file" not in ROLES["explorateur"].tools
