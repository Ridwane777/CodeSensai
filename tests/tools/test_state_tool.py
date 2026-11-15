"""
Tests the `update_state` tool - feature [M4], ADR-0029.

`test_declares_write_risk` protects A3: without it, a prompt injection
could make the agent write to SENSAI.md without confirmation.
"""
from sensai.core.tools import ToolRegistry
from sensai.execution.gateway import ToolGateway
from sensai.execution.tool_policy import Risk, risk_of
from sensai.knowledge.state_document import StateDocument
from sensai.tools.state_tool import UpdateStateTool


def make_tool(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return UpdateStateTool(StateDocument(project, tmp_path / "journal.jsonl"))


def test_declares_write_risk(tmp_path):
    assert risk_of(make_tool(tmp_path)) is Risk.WRITE


def test_updates_and_returns_the_diff(tmp_path):
    t = make_tool(tmp_path)

    result = t.run(section="In progress", action="replace", content="- M4")

    assert result.ok
    assert "+- M4" in result.content
    assert "- M4" in t.document.path.read_text(encoding="utf-8")


def test_error_returned_cleanly_never_raised(tmp_path):
    t = make_tool(tmp_path)

    result = t.run(section="Roadmap", action="append", content="- x")

    assert not result.ok
    assert "In progress" in result.content


def test_confirmation_shows_before_and_after(tmp_path):
    """US-M4-3: what the user approves is the change itself."""
    t = make_tool(tmp_path)
    t.run(section="In progress", action="replace", content="- R2")

    plan = t.describe_call(section="In progress", action="replace", content="- M4")

    assert "-- R2" in plan and "+- M4" in plan


def test_gateway_asks_confirmation_and_refusal_changes_nothing(tmp_path):
    t = make_tool(tmp_path)
    registry = ToolRegistry()
    registry.register(t)
    requests = []
    gateway = ToolGateway(registry, confirm=lambda req: requests.append(req) or False)

    result = gateway.call("update_state", section="Done", action="append", content="- x")

    assert len(requests) == 1
    assert "+- x" in requests[0].summary
    assert not result.ok
    assert not t.document.path.exists()
