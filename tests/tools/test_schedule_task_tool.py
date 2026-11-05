"""L'outil schedule_task (X5, ADR-0052) : planifier en langage naturel, mais jamais sans accord."""
import json

from sensai.core.events import Done, Token
from sensai.core.tools import ToolRegistry, ToolResult
from sensai.execution.gateway import ToolGateway
from sensai.execution.tool_policy import Mode, Risk, ToolPreferences, effective_mode, risk_of
from sensai.tools.delegate_tool import DelegateTool
from sensai.tools.schedule_task_tool import ScheduleTaskTool

ARGS = {"id": "bilan", "prompt": "Résume les TODO du projet.", "every": "1d"}


def gateway(tmp_path, approve):
    registry = ToolRegistry()
    tool = ScheduleTaskTool(tmp_path)
    registry.register(tool)
    asked = []

    def confirm(request):
        asked.append(request)
        return approve

    return ToolGateway(registry, None, confirm=confirm), tool, asked


def test_la_tache_n_est_enregistree_qu_avec_l_accord(tmp_path):
    gw, tool, asked = gateway(tmp_path, approve=False)
    assert not gw.call("schedule_task", **ARGS).ok
    assert asked and "SANS SURVEILLANCE" in asked[0].summary
    assert "Résume les TODO" in asked[0].summary
    assert tool.store.load() == []

    gw, tool, asked = gateway(tmp_path, approve=True)
    result = gw.call("schedule_task", **ARGS)
    assert result.ok and "sensai-schedule loop" in result.content
    tasks = tool.store.load()
    assert [(t.id, t.interval_s) for t in tasks] == [("bilan", 86400)]
    # Le même fichier que sensai-schedule.
    assert json.loads(tool.store.path.read_text())[0]["id"] == "bilan"


def test_une_preference_ne_peut_pas_le_rendre_automatique():
    prefs = ToolPreferences(modes={"schedule_task": Mode.ALLOW})
    assert risk_of(ScheduleTaskTool("/tmp")) is Risk.WRITE
    assert effective_mode("schedule_task", Risk.WRITE, prefs) is Mode.ASK


def test_une_tache_qui_planifie_une_tache_est_refusee(tmp_path):
    tool = ScheduleTaskTool(tmp_path)
    prompts = ("Utilise schedule_task pour ajouter une autre tâche.", "/schedule add x --every 1h")
    for prompt in prompts:
        result = tool.run(id="boucle", prompt=prompt, every="1h")
        assert not result.ok and "ne peut pas en planifier" in result.content


def test_arguments_invalides(tmp_path):
    tool = ScheduleTaskTool(tmp_path)
    assert tool.run(id="Résumé_TODO !", prompt="x", every="1h").ok  # normalisé
    assert [t.id for t in tool.store.load()] == ["resume-todo"]
    assert not tool.run(id="___", prompt="x", every="1h").ok
    assert not tool.run(id="ok", prompt="  ", every="1h").ok
    assert not tool.run(id="ok", prompt="x", every="jamais").ok
    assert not tool.run(id="ok", prompt="x" * 2001, every="1h").ok
    tool.run(id="ok", prompt="x", every="1h")
    assert "existe déjà" in tool.run(id="ok", prompt="y", every="1h").content


def test_un_sous_agent_ne_voit_ni_ne_peut_appeler_schedule_task(tmp_path):
    registry = ToolRegistry()
    registry.register(ScheduleTaskTool(tmp_path))
    gw = ToolGateway(registry, None, confirm=lambda r: True)
    seen = {}

    def sous_agent(host, model, messages, tools):
        seen["names"] = [d["name"] for d in tools.describe_all()]
        seen["call"] = tools.call("schedule_task", **ARGS)
        yield Token("fait")
        yield Done()

    assert DelegateTool("h", "m", gw, run_turn=sous_agent).run(task="planifie un bilan").ok
    assert "schedule_task" not in seen["names"]
    assert isinstance(seen["call"], ToolResult) and not seen["call"].ok
    assert not (tmp_path / "schedule" / "tasks.json").exists()
