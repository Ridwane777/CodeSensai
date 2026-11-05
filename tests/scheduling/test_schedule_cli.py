"""Teste la commande `sensai-schedule` de bout en bout — feature [X5], ADR-0016."""
import json

import pytest

from sensai import schedule_cli
from sensai.core.events import Done, Token
from sensai.core.tools import ToolRegistry
from sensai.scheduling.runner import list_runs
from sensai.scheduling.tasks import TaskStore

from .helpers import FakeTool, say


@pytest.fixture
def data(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def agent_calls(monkeypatch):
    """Remplace l'agent par un faux et note les prompts reçus."""
    calls = []

    def agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
        calls.append(messages[-1]["content"])
        if "casse" in messages[-1]["content"]:
            raise RuntimeError("panne interne")
        yield Token(text="réponse")
        yield Done()

    monkeypatch.setattr(schedule_cli, "run_agent_turn", agent)
    return calls


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    registry = ToolRegistry()
    registry.register(FakeTool("lire", "read"))
    monkeypatch.setattr(schedule_cli, "build_registry", lambda permissions=None: registry)
    return registry


def cli(data, *args):
    return schedule_cli.main(["--data-dir", str(data), *args])


def base(data):
    return data / "schedule"


def test_does_not_use_get_settings_which_parses_sys_argv():
    assert not hasattr(schedule_cli, "get_settings")


def test_add_list_remove(data, capsys):
    assert cli(data, "add", "resume", "--every", "1d", "--prompt", "Résume le journal") == 0
    assert cli(data, "list") == 0
    out = capsys.readouterr().out
    assert "resume" in out and "1d" in out and "maintenant" in out

    assert TaskStore(base(data) / "tasks.json").get("resume").prompt == "Résume le journal"
    assert cli(data, "remove", "resume") == 0
    assert TaskStore(base(data) / "tasks.json").load() == []
    assert cli(data, "list") == 0
    assert "Aucune tâche" in capsys.readouterr().out


def test_remove_deletes_the_run_records(data, agent_calls):
    cli(data, "add", "a", "--every", "1h", "--prompt", "p")
    cli(data, "run-due")
    assert len(list_runs(base(data), "a")) == 1
    assert cli(data, "remove", "a") == 0
    assert list_runs(base(data), "a") == []
    assert not (base(data) / "runs" / "a").exists()


def test_add_refuses_duplicates_bad_intervals_bad_ids_and_unknown_tools(data, capsys):
    assert cli(data, "add", "a", "--every", "1h", "--prompt", "p") == 0
    assert cli(data, "add", "a", "--every", "2h", "--prompt", "p") == 1
    assert "existe déjà" in capsys.readouterr().err
    assert cli(data, "add", "b", "--every", "30s", "--prompt", "p") == 2
    assert "trop court" in capsys.readouterr().err
    assert cli(data, "add", "../x", "--every", "1h", "--prompt", "p") == 2
    assert cli(data, "add", "c", "--every", "1h", "--prompt", "p", "--tools", "lire,inconnu") == 2
    assert "inconnu" in capsys.readouterr().err
    assert [t.id for t in TaskStore(base(data) / "tasks.json").load()] == ["a"]


def test_add_with_tools_allowlist(data):
    assert cli(data, "add", "a", "--every", "1h", "--prompt", "p", "--tools", "lire",
               "--timeout", "30") == 0
    task = TaskStore(base(data) / "tasks.json").get("a")
    assert task.tools == ["lire"] and task.timeout_s == 30


def test_run_due_runs_each_due_task_once_then_nothing(data, agent_calls, capsys):
    cli(data, "add", "a", "--every", "1h", "--prompt", "premier")
    cli(data, "add", "b", "--every", "1h", "--prompt", "second")
    capsys.readouterr()

    assert cli(data, "run-due") == 0
    assert agent_calls == ["premier", "second"]
    assert "a : ok" in capsys.readouterr().out
    assert len(list_runs(base(data), "a")) == 1

    assert cli(data, "run-due") == 0
    assert agent_calls == ["premier", "second"]  # rien de plus
    assert "Aucune tâche échue" in capsys.readouterr().out


def test_dry_run_lists_without_running_or_writing(data, agent_calls, capsys):
    cli(data, "add", "a", "--every", "1h", "--prompt", "p")
    capsys.readouterr()
    assert cli(data, "run-due", "--dry-run") == 0
    assert capsys.readouterr().out.strip() == "a"
    assert agent_calls == []
    assert TaskStore(base(data) / "tasks.json").get("a").last_run_at is None


def test_failing_task_exits_1_but_the_others_still_run(data, agent_calls, capsys):
    cli(data, "add", "a", "--every", "1h", "--prompt", "casse tout")
    cli(data, "add", "b", "--every", "1h", "--prompt", "tranquille")
    capsys.readouterr()

    assert cli(data, "run-due") == 1

    out = capsys.readouterr().out
    assert "a : error" in out and "b : ok" in out
    assert list_runs(base(data), "a")[0]["status"] == "error"
    assert list_runs(base(data), "b")[0]["status"] == "ok"


def test_run_forces_a_task_that_is_not_due(data, agent_calls):
    cli(data, "add", "a", "--every", "1d", "--prompt", "p")
    cli(data, "run-due")
    assert cli(data, "run", "a") == 0
    assert len(agent_calls) == 2
    assert cli(data, "run", "inconnue") == 1


def test_disable_and_enable(data, agent_calls, capsys):
    cli(data, "add", "a", "--every", "1h", "--prompt", "p")
    assert cli(data, "disable", "a") == 0
    cli(data, "run-due")
    assert agent_calls == []
    assert cli(data, "enable", "a") == 0
    cli(data, "run-due")
    assert agent_calls == ["p"]
    assert cli(data, "disable", "zzz") == 1


def test_history_shows_latest_first_and_limits(data, agent_calls, capsys):
    cli(data, "add", "a", "--every", "1h", "--prompt", "p")
    for _ in range(3):
        cli(data, "run", "a")
    capsys.readouterr()
    assert cli(data, "history", "a", "-n", "2") == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2 and all("ok" in line for line in lines)
    assert cli(data, "history", "zzz") == 1


@pytest.mark.parametrize(
    "args",
    [["list"], ["run-due"], ["run-due", "--dry-run"], ["run", "a"], ["remove", "a"],
     ["disable", "a"], ["history", "a"], ["add", "b", "--every", "1h", "--prompt", "p"]],
)
def test_corrupt_task_file_exits_2_names_the_file_and_is_untouched(
    data, agent_calls, capsys, args
):
    path = base(data) / "tasks.json"
    path.parent.mkdir(parents=True)
    content = b'[{"id": "a", "prompt": '  # JSON tronqué
    path.write_bytes(content)

    code = cli(data, *args)

    err = capsys.readouterr().err
    assert code == 2
    assert str(path) in err and "tasks.json" in err
    assert "n'a pas été modifié" in err
    assert path.read_bytes() == content
    assert agent_calls == []


def test_invalid_tools_section_in_config_is_a_clean_error(data, monkeypatch, capsys):
    monkeypatch.setattr(schedule_cli, "load_config_file", lambda: {"tools": {"modes": {"x": "?"}}})
    cli(data, "add", "a", "--every", "1h", "--prompt", "p")
    assert cli(data, "run-due") == 2
    assert "Mode invalide" in capsys.readouterr().err


def test_loop_passes_the_pause_to_the_scheduler(data, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        schedule_cli.Scheduler, "loop", lambda self, every, *a, **k: seen.update(every=every)
    )
    assert cli(data, "loop", "--every", "5m") == 0
    assert seen == {"every": 300}
    assert cli(data, "loop", "--every", "10") == 2  # moins d'une minute


def test_loop_stops_cleanly_on_ctrl_c(data, monkeypatch, capsys):
    def interrupted(self, every, *a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(schedule_cli.Scheduler, "loop", interrupted)
    assert cli(data, "loop") == 0
    assert "Arrêt" in capsys.readouterr().out


def test_models_and_host_come_from_options_over_config(data, monkeypatch):
    seen = {}

    def agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
        seen.update(host=host, model=model)
        yield Done()

    monkeypatch.setattr(schedule_cli, "run_agent_turn", agent)
    monkeypatch.setattr(
        schedule_cli, "load_config_file", lambda: {"model": "du-config", "host": "http://c"}
    )
    cli(data, "add", "a", "--every", "1h", "--prompt", "p")
    cli(data, "run-due")
    assert seen == {"host": "http://c", "model": "du-config"}
    seen.clear()
    schedule_cli.main(["--data-dir", str(data), "--model", "x", "--host", "http://h", "run", "a"])
    assert seen == {"host": "http://h", "model": "x"}


def test_say_helper_is_usable_as_an_agent(data, monkeypatch):
    monkeypatch.setattr(schedule_cli, "run_agent_turn", say("ok"))
    cli(data, "add", "a", "--every", "1h", "--prompt", "p")
    assert cli(data, "run-due") == 0
    record = list_runs(base(data), "a")[0]
    assert json.dumps(record)  # sérialisable
    assert record["answer"] == "ok"


@pytest.mark.parametrize(
    "args",
    [["history", "../x"], ["remove", "../x"], ["run", "../x"], ["enable", "../x"],
     ["disable", "../x"], ["history", "../../x"], ["remove", "a/b"], ["history", "/etc"]],
)
def test_path_like_ids_are_refused_before_touching_the_disk(data, tmp_path, capsys, args):
    outside = tmp_path / "x"  # data/schedule/../x ne sort pas de data, mais ../../x oui
    (data / "x").mkdir(parents=True)
    (data / "x" / "secret.json").write_text('{"started_at": "s"}', encoding="utf-8")
    outside.mkdir()
    (outside / "secret.json").write_text('{"started_at": "s"}', encoding="utf-8")

    assert cli(data, *args) == 2

    assert "Identifiant invalide" in capsys.readouterr().err
    assert (data / "x" / "secret.json").exists() and (outside / "secret.json").exists()


def test_runs_path_and_lock_path_refuse_unsafe_ids(tmp_path):
    from sensai.scheduling.runner import lock_path, runs_path

    for bad in ("../x", "a/b", ""):
        with pytest.raises(ValueError):
            runs_path(tmp_path, bad)
        with pytest.raises(ValueError):
            lock_path(tmp_path, bad)


def test_num_ctx_de_la_config_part_avec_l_agent_planifie(data, monkeypatch):
    """Revue PR #97 : `sensai-schedule` oubliait `num_ctx`."""
    vus = []

    def agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
        vus.append(num_ctx)
        yield Done()

    monkeypatch.setattr(schedule_cli, "run_agent_turn", agent)
    monkeypatch.setattr(schedule_cli, "load_config_file", lambda: {"num_ctx": 4096})
    cli(data, "add", "a", "--every", "1h", "--prompt", "p")
    cli(data, "run-due")
    assert vus == [4096]


def test_num_ctx_invalide_dans_la_config_est_une_erreur_propre(data, monkeypatch, capsys):
    monkeypatch.setattr(schedule_cli, "load_config_file", lambda: {"num_ctx": "grand"})
    cli(data, "add", "a", "--every", "1h", "--prompt", "p")
    assert cli(data, "run-due") == 2
    assert "num_ctx" in capsys.readouterr().err
