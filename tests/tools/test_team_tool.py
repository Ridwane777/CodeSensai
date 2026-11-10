"""Tests the `team_task` team — feature [A2], ADR-0038.

The sub-agents are fake turns (no Ollama): each answers according to its role,
recognized by its instructions in the system message.
"""
import itertools

from sensai.core.events import Done, Token
from sensai.execution.tool_policy import Risk, risk_of
from sensai.tools import team_tool
from sensai.tools.delegate_tool import ROLES, DelegateTool, _depth
from sensai.tools.team_tool import TeamTool, verdict


def team(answers, notes=None):
    """A team where each role answers, in order, with the given texts."""
    queues = {role: iter(texts) for role, texts in answers.items()}
    received = []

    def sub_agent(host, model, messages, tools):
        role = next(r for r, spec in ROLES.items() if spec.prompt in messages[0]["content"])
        received.append((role, messages[-1]["content"]))
        yield Token(text=next(queues[role]))
        yield Done()

    delegate = DelegateTool("h", "m", tools=None, run_turn=sub_agent)
    return TeamTool(delegate, notify=(notes.append if notes is not None else None)), received


def test_declares_execute_risk():
    assert risk_of(TeamTool(DelegateTool("h", "m", tools=None))) is Risk.EXECUTE


def test_work_goes_from_explorer_to_developer_then_reviewer():
    tool, received = team({
        "explorateur": ["EXPLORER-REPORT"],
        "developpeur": ["DEV-CODE"],
        "relecteur": ["APPROVED, nothing to add"],
    })

    result = tool.run(task="add a function")

    assert [r for r, _ in received] == ["explorateur", "developpeur", "relecteur"]
    assert "EXPLORER-REPORT" in received[1][1]  # the developer receives the report
    assert "DEV-CODE" in received[2][1]  # the reviewer receives the work
    assert result.ok
    assert result.content.startswith(
        "Path: explorateur → developpeur → relecteur; reviewer verdict: approved."
    )


def test_needs_fix_sends_back_to_developer_with_critique_only_once():
    tool, received = team({
        "explorateur": ["REPORT"],
        "developpeur": ["V1", "V2"],
        "relecteur": ["NEEDS FIX: the test is missing", "NEEDS FIX: again"],
    })

    result = tool.run(task="t")

    assert [r for r, _ in received] == [
        "explorateur", "developpeur", "relecteur", "developpeur", "relecteur"]
    assert "the test is missing" in received[3][1] and "V1" in received[3][1]
    # the chain went all the way: a result (not a failure) the agent passes on
    assert result.ok and "reviewer verdict: needs fix" in result.content
    assert "do not restart the team" in result.content


def test_each_handoff_is_announced():
    notes = []
    tool, _ = team({"explorateur": ["r"], "developpeur": ["c"], "relecteur": ["APPROVED"]}, notes)

    tool.run(task="t")

    assert notes == ["team: explorateur at work", "handoff: explorateur → developpeur",
                     "handoff: developpeur → relecteur"]


def test_the_chain_stops_and_says_so_when_time_runs_out(monkeypatch):
    # start at 0; when the reviewer turn comes, less than MIN_STEP_S is left
    budget = team_tool.DELEGATION_TIMEOUT_S - team_tool.STOP_MARGIN_S
    clock = itertools.chain([0.0, 1.0, 2.0, 3.0, 4.0], itertools.repeat(budget - 1))
    now = lambda: next(clock)  # noqa: E731
    monkeypatch.setattr(team_tool.time, "monotonic", now)
    monkeypatch.setattr("sensai.tools.delegate_tool.time.monotonic", now)
    tool, received = team({"explorateur": ["r"], "developpeur": ["c"], "relecteur": ["APPROVED"]})

    result = tool.run(task="t")

    assert "relecteur" not in [r for r, _ in received]
    assert not result.ok and "for lack of time before the reviewer" in result.content


def test_a_sub_agent_does_not_start_a_team():
    tool, received = team({})
    token = _depth.set(1)
    try:
        result = tool.run(task="t")
    finally:
        _depth.reset(token)
    assert not result.ok and received == []


def test_empty_task_rejected():
    tool, received = team({})
    assert not tool.run(task="  ").ok and received == []


def test_verdict():
    assert verdict("APPROVED: correct") == "approved"
    assert verdict("**Approved**") == "approved"
    assert verdict("NEEDS FIX\n- bug") == "needs fix"
    assert verdict("needs fix: x") == "needs fix"
    assert verdict("The code looks fine to me") == "unreadable"
    # French answers stay accepted (the model may reply in the user language).
    assert verdict("VALIDÉ : correct") == "approved"
    assert verdict("À CORRIGER\n- bug") == "needs fix"


def test_on_handoff_receives_each_role_taking_over():
    """X1: the web turns these calls into `agent_handoff` events."""
    from sensai.core.tools import ToolResult

    class FakeDelegate:
        def delegate(self, instruction, *, role, deadline, on_call):
            return ToolResult(ok=True, content="APPROVED." if role == "relecteur" else "ok")

    roles = []
    TeamTool(FakeDelegate(), on_handoff=roles.append).run(task="Fix it")
    assert roles == ["explorateur", "developpeur", "relecteur"]


def test_misplaced_detects_a_file_created_in_the_wrong_place():
    """Trial run of 2026-11-01: "add mediane to stats.py" → src/sensai/stats.py created."""
    from sensai.tools.team_tool import misplaced, named_files

    task = "Add a mediane(notes) function to stats.py."
    assert named_files(task) == {"stats.py"}
    assert misplaced(task, {"src/sensai/stats.py"}) == [("src/sensai/stats.py", "stats.py")]
    assert misplaced(task, {"stats.py"}) == []          # the right file
    assert misplaced(task, {"./stats.py"}) == []
    assert misplaced(task, {"tests/test_stats.py"}) == []  # different name: nothing to flag
    assert misplaced("Create src/app/main.py", {"src/app/main.py"}) == []


def test_a_file_created_in_the_wrong_place_is_sent_back_without_review():
    from sensai.core.tools import ToolResult

    calls = []

    class FakeDelegate:
        def delegate(self, instruction, *, role, deadline, on_call):
            calls.append(role)
            if role == "developpeur":
                path = "src/sensai/stats.py" if calls.count("developpeur") == 1 else "stats.py"
                verb = "Created" if path != "stats.py" else "Replaced"
                on_call("write_file", {"path": path, "content": "def mediane(n): ..."},
                        ToolResult(ok=True, content=f"{verb} {path}"))
            return ToolResult(ok=True, content="APPROVED." if role == "relecteur" else "done")

    result = TeamTool(FakeDelegate()).run(task="Add a mediane(notes) function to stats.py.")
    # 1st attempt sent back without reviewer; the fix writes stats.py; then the reviewer judges.
    assert calls == ["explorateur", "developpeur", "developpeur", "relecteur"]
    assert "approved" in result.content and "wrong place" not in result.content


def test_a_file_still_misplaced_is_never_approved():
    from sensai.core.tools import ToolResult

    class FakeDelegate:
        def delegate(self, instruction, *, role, deadline, on_call):
            if role == "developpeur":
                on_call("write_file", {"path": "src/sensai/stats.py", "content": "x"},
                        ToolResult(ok=True, content="Created src/sensai/stats.py"))
            return ToolResult(ok=True, content="APPROVED." if role == "relecteur" else "done")

    result = TeamTool(FakeDelegate()).run(task="Add a mediane(notes) function to stats.py.")
    assert "wrong place" in result.content and "stats.py" in result.content
    assert "reviewer verdict: approved" not in result.content


# --- Project tests as the verdict (ADR-0056, point 3) ------------------------------

def team_with_tests(answers, results, writes=True):
    """A team whose verdict comes from a fake project test runner; the
    developer writes stats.py on every pass (unless `writes=False`)."""
    from sensai.core.tools import ToolResult

    queues = {role: iter(texts) for role, texts in answers.items()}
    received = []

    class FakeDelegate:
        def delegate(self, instruction, *, role, deadline, on_call):
            received.append((role, instruction))
            text = next(queues[role])
            if role == "developpeur" and writes:
                on_call("write_file", {"path": "stats.py", "content": text},
                        ToolResult(ok=True, content="Replaced stats.py"))
            return ToolResult(ok=True, content=text)

    tool = TeamTool(FakeDelegate())
    runs = iter(results)
    tool.test_runner = lambda: next(runs)
    return tool, received


def test_without_a_modified_file_tests_do_not_approve():
    """Trial run of 2026-11-06: the developer write is refused, the project has not
    changed, its tests pass... and the team announced "approved"."""
    runs_made = []
    tool, received = team_with_tests({"explorateur": ["R"], "developpeur": ["V1", "V2"]},
                                      [], writes=False)
    tool.test_runner = lambda: runs_made.append(1) or (True, "1 passed")

    result = tool.run(task="moyenne([]) must raise ValueError")

    assert runs_made == [], "the tests of an unchanged project are not run"
    assert [r for r, _ in received] == ["explorateur", "developpeur", "developpeur"]
    assert "No file was modified" in received[2][1]
    assert "approved" not in result.content
    assert "no file modified" in result.content


def test_passing_tests_approve_without_reviewer():
    tool, received = team_with_tests({"explorateur": ["R"], "developpeur": ["CODE"]},
                                      [(True, "3 passed")])

    result = tool.run(task="add mediane")

    assert [r for r, _ in received] == ["explorateur", "developpeur"]
    assert "project tests verdict: approved" in result.content
    assert "3 passed" in result.content


def test_failing_tests_send_the_output_back_to_the_developer():
    tool, received = team_with_tests({"explorateur": ["R"], "developpeur": ["V1", "V2"]},
                                      [(False, "FAILED test_stats.py::test_mediane"),
                                       (True, "4 passed")])

    result = tool.run(task="add mediane")

    assert [r for r, _ in received] == ["explorateur", "developpeur", "developpeur"]
    assert "FAILED test_stats.py::test_mediane" in received[2][1]
    assert "project tests verdict: approved" in result.content


def test_the_real_runner_runs_pytest_in_the_project(tmp_path, monkeypatch):
    from sensai.tools.project_tests import project_test_runner

    monkeypatch.delenv("SENSAI_NO_PROJECT_TESTS", raising=False)

    assert project_test_runner(tmp_path) is None  # no tests: the reviewer stays in charge
    (tmp_path / "test_ok.py").write_text("def test_un():\n    assert 1 + 1 == 2\n")
    passed, output = project_test_runner(tmp_path)()
    assert passed and "1 passed" in output
    (tmp_path / "test_ko.py").write_text("def test_deux():\n    assert 1 + 1 == 3\n")
    passed, output = project_test_runner(tmp_path)()
    assert not passed and "failed" in output


def test_tests_run_by_the_team_do_not_start_another_team(tmp_path, monkeypatch):
    """Seen on 2026-11-02: without a guard, each pytest level restarted a team that
    restarted pytest. The team pytest receives SENSAI_NO_PROJECT_TESTS."""
    from sensai.tools.project_tests import project_test_runner

    monkeypatch.delenv("SENSAI_NO_PROJECT_TESTS", raising=False)
    (tmp_path / "test_env.py").write_text(
        "import os\n\n"
        "def test_guard():\n"
        "    assert os.environ.get('SENSAI_NO_PROJECT_TESTS') == '1'\n")
    passed, output = project_test_runner(tmp_path)()
    assert passed, output
    monkeypatch.setenv("SENSAI_NO_PROJECT_TESTS", "1")
    assert project_test_runner(tmp_path) is None
