"""Teste l'équipe `team_task` — feature [A2], ADR-0038.

Les sous-agents sont de faux tours (pas d'Ollama) : chacun répond selon son
rôle, reconnu à ses consignes dans le message système.
"""
import itertools

from sensai.core.events import Done, Token
from sensai.execution.tool_policy import Risk, risk_of
from sensai.tools import team_tool
from sensai.tools.delegate_tool import ROLES, DelegateTool, _depth
from sensai.tools.team_tool import TeamTool, verdict


def team(answers, notes=None):
    """Une équipe dont chaque rôle répond, dans l'ordre, par les textes donnés."""
    queues = {role: iter(texts) for role, texts in answers.items()}
    received = []

    def sub_agent(host, model, messages, tools):
        role = next(r for r, spec in ROLES.items() if spec.prompt in messages[0]["content"])
        received.append((role, messages[-1]["content"]))
        yield Token(text=next(queues[role]))
        yield Done()

    delegate = DelegateTool("h", "m", tools=None, run_turn=sub_agent)
    return TeamTool(delegate, notify=(notes.append if notes is not None else None)), received


def test_declare_le_risque_execute():
    assert risk_of(TeamTool(DelegateTool("h", "m", tools=None))) is Risk.EXECUTE


def test_le_travail_passe_de_l_explorateur_au_developpeur_puis_au_relecteur():
    outil, received = team({
        "explorateur": ["RAPPORT-EXPLO"],
        "developpeur": ["CODE-DEV"],
        "relecteur": ["VALIDÉ, rien à redire"],
    })

    result = outil.run(task="ajoute une fonction")

    assert [r for r, _ in received] == ["explorateur", "developpeur", "relecteur"]
    assert "RAPPORT-EXPLO" in received[1][1]  # le développeur reçoit le rapport
    assert "CODE-DEV" in received[2][1]  # le relecteur reçoit le travail
    assert result.ok
    assert result.content.startswith(
        "Chemin : explorateur → developpeur → relecteur ; verdict du relecteur : validé."
    )


def test_a_corriger_renvoie_au_developpeur_avec_la_critique_une_seule_fois():
    outil, received = team({
        "explorateur": ["RAPPORT"],
        "developpeur": ["V1", "V2"],
        "relecteur": ["À CORRIGER : il manque le test", "À CORRIGER : encore"],
    })

    result = outil.run(task="t")

    assert [r for r, _ in received] == [
        "explorateur", "developpeur", "relecteur", "developpeur", "relecteur"]
    assert "il manque le test" in received[3][1] and "V1" in received[3][1]
    # la chaîne est allée au bout : un résultat (pas une panne) que l'agent transmet
    assert result.ok and "verdict du relecteur : à corriger" in result.content
    assert "ne relance pas l'équipe" in result.content


def test_chaque_relais_est_annonce():
    notes = []
    outil, _ = team({"explorateur": ["r"], "developpeur": ["c"], "relecteur": ["VALIDÉ"]}, notes)

    outil.run(task="t")

    assert notes == ["équipe : explorateur au travail", "relais : explorateur → developpeur",
                     "relais : developpeur → relecteur"]


def test_la_chaine_s_arrete_et_le_dit_quand_le_temps_manque(monkeypatch):
    # départ à 0 ; quand vient le tour du relecteur, il reste moins de MIN_STEP_S
    budget = team_tool.DELEGATION_TIMEOUT_S - team_tool.STOP_MARGIN_S
    clock = itertools.chain([0.0, 1.0, 2.0, 3.0, 4.0], itertools.repeat(budget - 1))
    now = lambda: next(clock)  # noqa: E731
    monkeypatch.setattr(team_tool.time, "monotonic", now)
    monkeypatch.setattr("sensai.tools.delegate_tool.time.monotonic", now)
    outil, received = team({"explorateur": ["r"], "developpeur": ["c"], "relecteur": ["VALIDÉ"]})

    result = outil.run(task="t")

    assert "relecteur" not in [r for r, _ in received]
    assert not result.ok and "faute de temps avant le relecteur" in result.content


def test_un_sous_agent_ne_lance_pas_d_equipe():
    outil, received = team({})
    token = _depth.set(1)
    try:
        result = outil.run(task="t")
    finally:
        _depth.reset(token)
    assert not result.ok and received == []


def test_tache_vide_refusee():
    outil, received = team({})
    assert not outil.run(task="  ").ok and received == []


def test_verdict():
    assert verdict("VALIDÉ : correct") == "validé"
    assert verdict("**Validé**") == "validé"
    assert verdict("À CORRIGER\n- bug") == "à corriger"
    assert verdict("a corriger : x") == "à corriger"
    assert verdict("Le code me semble bon") == "illisible"


def test_on_handoff_recoit_chaque_role_qui_prend_la_main():
    """X1 : le web transforme ces appels en événements `agent_handoff`."""
    from sensai.core.tools import ToolResult

    class Delegue:
        def delegate(self, consigne, *, role, deadline, on_call):
            return ToolResult(ok=True, content="VALIDÉ." if role == "relecteur" else "ok")

    roles = []
    TeamTool(Delegue(), on_handoff=roles.append).run(task="Corrige")
    assert roles == ["explorateur", "developpeur", "relecteur"]


def test_misplaced_repere_un_fichier_cree_au_mauvais_endroit():
    """Essai du 2026-11-01 : « ajoute mediane à stats.py » → src/sensai/stats.py créé."""
    from sensai.tools.team_tool import misplaced, named_files

    task = "Ajoute à stats.py une fonction mediane(notes)."
    assert named_files(task) == {"stats.py"}
    assert misplaced(task, {"src/sensai/stats.py"}) == [("src/sensai/stats.py", "stats.py")]
    assert misplaced(task, {"stats.py"}) == []          # le bon fichier
    assert misplaced(task, {"./stats.py"}) == []
    assert misplaced(task, {"tests/test_stats.py"}) == []  # autre nom : rien à redire
    assert misplaced("Crée src/app/main.py", {"src/app/main.py"}) == []


def test_un_fichier_cree_au_mauvais_endroit_est_renvoye_sans_relecture():
    from sensai.core.tools import ToolResult

    calls = []

    class Delegue:
        def delegate(self, consigne, *, role, deadline, on_call):
            calls.append(role)
            if role == "developpeur":
                path = "src/sensai/stats.py" if calls.count("developpeur") == 1 else "stats.py"
                verb = "Created" if path != "stats.py" else "Replaced"
                on_call("write_file", {"path": path, "content": "def mediane(n): ..."},
                        ToolResult(ok=True, content=f"{verb} {path}"))
            return ToolResult(ok=True, content="VALIDÉ." if role == "relecteur" else "fait")

    result = TeamTool(Delegue()).run(task="Ajoute à stats.py une fonction mediane(notes).")
    # 1er essai renvoyé sans relecteur ; la correction écrit stats.py ; puis le relecteur juge.
    assert calls == ["explorateur", "developpeur", "developpeur", "relecteur"]
    assert "validé" in result.content and "mauvais endroit" not in result.content


def test_un_fichier_toujours_mal_place_n_est_jamais_valide():
    from sensai.core.tools import ToolResult

    class Delegue:
        def delegate(self, consigne, *, role, deadline, on_call):
            if role == "developpeur":
                on_call("write_file", {"path": "src/sensai/stats.py", "content": "x"},
                        ToolResult(ok=True, content="Created src/sensai/stats.py"))
            return ToolResult(ok=True, content="VALIDÉ." if role == "relecteur" else "fait")

    result = TeamTool(Delegue()).run(task="Ajoute à stats.py une fonction mediane(notes).")
    assert "mauvais endroit" in result.content and "stats.py" in result.content
    assert "verdict du relecteur : validé" not in result.content


# --- Les tests du projet comme verdict (ADR-0056, point 3) --------------------------

def team_with_tests(answers, results):
    """Une équipe dont le verdict vient d'un faux lanceur de tests du projet."""
    outil, received = team(answers)
    runs = iter(results)
    outil.test_runner = lambda: next(runs)
    return outil, received


def test_des_tests_qui_passent_valident_sans_relecteur():
    outil, received = team_with_tests({"explorateur": ["R"], "developpeur": ["CODE"]},
                                      [(True, "3 passed")])

    result = outil.run(task="ajoute mediane")

    assert [r for r, _ in received] == ["explorateur", "developpeur"]
    assert "verdict des tests du projet : validé" in result.content
    assert "3 passed" in result.content


def test_des_tests_qui_echouent_renvoient_la_sortie_au_developpeur():
    outil, received = team_with_tests({"explorateur": ["R"], "developpeur": ["V1", "V2"]},
                                      [(False, "FAILED test_stats.py::test_mediane"),
                                       (True, "4 passed")])

    result = outil.run(task="ajoute mediane")

    assert [r for r, _ in received] == ["explorateur", "developpeur", "developpeur"]
    assert "FAILED test_stats.py::test_mediane" in received[2][1]
    assert "verdict des tests du projet : validé" in result.content


def test_le_lanceur_reel_lance_pytest_dans_le_projet(tmp_path, monkeypatch):
    from sensai.tools.project_tests import project_test_runner

    monkeypatch.delenv("SENSAI_NO_PROJECT_TESTS", raising=False)

    assert project_test_runner(tmp_path) is None  # pas de tests : le relecteur garde la main
    (tmp_path / "test_ok.py").write_text("def test_un():\n    assert 1 + 1 == 2\n")
    passed, output = project_test_runner(tmp_path)()
    assert passed and "1 passed" in output
    (tmp_path / "test_ko.py").write_text("def test_deux():\n    assert 1 + 1 == 3\n")
    passed, output = project_test_runner(tmp_path)()
    assert not passed and "failed" in output


def test_les_tests_lances_par_l_equipe_ne_relancent_pas_d_equipe(tmp_path, monkeypatch):
    """Vu le 2026-11-02 : sans garde, chaque niveau de pytest relançait une équipe qui
    relançait pytest. Le pytest de l'équipe reçoit SENSAI_NO_PROJECT_TESTS."""
    from sensai.tools.project_tests import project_test_runner

    monkeypatch.delenv("SENSAI_NO_PROJECT_TESTS", raising=False)
    (tmp_path / "test_env.py").write_text(
        "import os\n\n"
        "def test_garde():\n"
        "    assert os.environ.get('SENSAI_NO_PROJECT_TESTS') == '1'\n")
    passed, output = project_test_runner(tmp_path)()
    assert passed, output
    monkeypatch.setenv("SENSAI_NO_PROJECT_TESTS", "1")
    assert project_test_runner(tmp_path) is None
