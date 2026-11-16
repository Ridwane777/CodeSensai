"""The schedule_task tool (X5, ADR-0052).

Schedules in natural language, but never without approval.
"""
import json

from sensai.core.events import Done, Token
from sensai.core.tools import ToolRegistry, ToolResult
from sensai.execution.gateway import ToolGateway
from sensai.execution.tool_policy import Mode, Risk, ToolPreferences, effective_mode, risk_of
from sensai.tools.delegate_tool import DelegateTool
from sensai.tools.schedule_task_tool import ScheduleTaskTool

ARGS = {"id": "report", "prompt": "Summarize the project TODOs.", "every": "1d"}


def gateway(tmp_path, approve):
    registry = ToolRegistry()
    tool = ScheduleTaskTool(tmp_path)
    registry.register(tool)
    asked = []

    def confirm(request):
        asked.append(request)
        return approve

    return ToolGateway(registry, None, confirm=confirm), tool, asked


def test_task_is_saved_only_with_approval(tmp_path):
    gw, tool, asked = gateway(tmp_path, approve=False)
    assert not gw.call("schedule_task", **ARGS).ok
    assert asked and "UNATTENDED" in asked[0].summary
    assert "Summarize the project TODOs" in asked[0].summary
    assert tool.store.load() == []

    gw, tool, asked = gateway(tmp_path, approve=True)
    result = gw.call("schedule_task", **ARGS)
    assert result.ok and "sensai-schedule loop" in result.content
    tasks = tool.store.load()
    assert [(t.id, t.interval_s) for t in tasks] == [("report", 86400)]
    # The same file as sensai-schedule.
    assert json.loads(tool.store.path.read_text())[0]["id"] == "report"


def test_no_preference_can_make_it_automatic():
    prefs = ToolPreferences(modes={"schedule_task": Mode.ALLOW})
    assert risk_of(ScheduleTaskTool("/tmp")) is Risk.WRITE
    assert effective_mode("schedule_task", Risk.WRITE, prefs) is Mode.ASK


def test_task_that_schedules_a_task_is_refused(tmp_path):
    tool = ScheduleTaskTool(tmp_path)
    prompts = ("Use schedule_task to add another task.", "/schedule add x --every 1h")
    for prompt in prompts:
        result = tool.run(id="loop", prompt=prompt, every="1h")
        assert not result.ok and "cannot schedule other tasks" in result.content


def test_invalid_arguments(tmp_path):
    tool = ScheduleTaskTool(tmp_path)
    # normalized (accented input on purpose)
    assert tool.run(id="Résumé_TODO !", prompt="x", every="1h").ok
    assert [t.id for t in tool.store.load()] == ["resume-todo"]
    assert not tool.run(id="___", prompt="x", every="1h").ok
    assert not tool.run(id="ok", prompt="  ", every="1h").ok
    assert not tool.run(id="ok", prompt="x", every="never").ok
    assert not tool.run(id="ok", prompt="x" * 2001, every="1h").ok
    tool.run(id="ok", prompt="x", every="1h")
    assert "already exists" in tool.run(id="ok", prompt="y", every="1h").content


def test_sub_agent_neither_sees_nor_can_call_schedule_task(tmp_path):
    registry = ToolRegistry()
    registry.register(ScheduleTaskTool(tmp_path))
    gw = ToolGateway(registry, None, confirm=lambda r: True)
    seen = {}

    def sub_agent(host, model, messages, tools):
        seen["names"] = [d["name"] for d in tools.describe_all()]
        seen["call"] = tools.call("schedule_task", **ARGS)
        yield Token("done")
        yield Done()

    assert DelegateTool("h", "m", gw, run_turn=sub_agent).run(task="schedule a report").ok
    assert "schedule_task" not in seen["names"]
    assert isinstance(seen["call"], ToolResult) and not seen["call"].ok
    assert not (tmp_path / "schedule" / "tasks.json").exists()
