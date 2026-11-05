"""Teste l'outil `delegate_task` — feature [A2], ADR-0037.

`run_turn` est remplacé par un faux tour (pas d'Ollama) : chaque test ne
vérifie qu'un seul comportement de DelegateTool, la vraie boucle ReAct est
déjà testée par tests/core/test_agent.py.
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


def test_declare_le_risque_execute():
    assert risk_of(DelegateTool("h", "m", tools=object())) is Risk.EXECUTE


def test_renvoie_la_reponse_du_sous_agent():
    run_turn = fake_turn([Token(text="ré"), Token(text="sultat"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="fais X")

    assert result.ok
    assert result.content == "résultat"


def test_la_tache_devient_le_seul_message_utilisateur():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    outil.run(task="analyse ce fichier")

    assert run_turn.calls[0]["messages"] == [{"role": "user", "content": "analyse ce fichier"}]


def test_le_persona_part_en_message_systeme():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    outil.run(task="analyse ce fichier", persona="relectrice de sécurité")

    messages = run_turn.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "relectrice de sécurité"}
    assert messages[1] == {"role": "user", "content": "analyse ce fichier"}


def test_le_sous_agent_passe_par_la_meme_passerelle():
    class Gateway:
        def __init__(self):
            self.calls = []

        def describe_all(self):
            return [{"name": "read_file"}]

        def call(self, name, /, **kwargs):
            self.calls.append((name, kwargs))
            return ToolResult(ok=True, content="lu")

    def sub_agent(host, model, messages, tools):
        assert tools.describe_all() == [{"name": "read_file"}]
        yield Token(text=tools.call("read_file", path="a.py").content)
        yield Done()

    gateway = Gateway()
    result = DelegateTool("http://h", "m1", tools=gateway, run_turn=sub_agent).run(task="fais X")

    assert gateway.calls == [("read_file", {"path": "a.py"})]
    assert result.content == "lu"


def test_tache_vide_est_refusee_sans_appeler_le_sous_agent():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="   ")

    assert not result.ok
    assert run_turn.calls == []


def test_erreur_du_sous_agent_est_rapportee_sans_lever():
    run_turn = fake_turn([Error(message="Ollama en panne"), Done(reason="error")])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="fais X")

    assert not result.ok
    assert "Ollama en panne" in result.content


def test_max_iterations_est_signale_mais_le_contenu_est_garde():
    run_turn = fake_turn([Token(text="réponse partielle"), Done(reason="max_iterations")])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="fais X")

    assert result.ok
    assert "réponse partielle" in result.content
    assert "itérations" in result.content


def test_sans_reponse_est_un_echec():
    run_turn = fake_turn([Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    result = outil.run(task="fais X")

    assert not result.ok


def test_profondeur_de_delegation_est_bornee():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)
    token = _depth.set(MAX_DELEGATION_DEPTH)

    try:
        result = outil.run(task="fais X")
    finally:
        _depth.reset(token)

    assert not result.ok
    assert "Profondeur" in result.content
    assert run_turn.calls == []


def test_la_profondeur_est_remise_a_zero_apres_l_appel():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("http://h", "m1", tools="gateway", run_turn=run_turn)

    outil.run(task="fais X")

    assert _depth.get() == 0


def test_la_profondeur_est_bornee_a_travers_la_vraie_passerelle():
    """La passerelle exécute chaque outil dans un thread : la profondeur doit y
    suivre, sinon un sous-agent qui redélègue sans fin n'est jamais arrêté."""
    from sensai.core.tools import ToolRegistry
    from sensai.execution.gateway import ToolGateway

    launched = []

    def sub_agent(host, model, messages, tools):
        launched.append(messages[-1]["content"])
        if len(launched) > MAX_DELEGATION_DEPTH + 3:  # filet du test : jamais atteint
            yield Token(text="boucle")
            yield Done()
            return
        # La vraie passerelle, pas celle filtrée du sous-agent : le garde-fou de
        # profondeur reste le dernier rempart si le filtre était contourné.
        result = gateway.call("delegate_task", task="refais la même chose")
        yield Token(text=result.content)
        yield Done()

    registry = ToolRegistry()
    gateway = ToolGateway(registry, None, confirm=lambda request: True)
    registry.register(DelegateTool("h", "m", gateway, run_turn=sub_agent))

    result = gateway.call("delegate_task", task="tâche de départ")

    assert len(launched) == MAX_DELEGATION_DEPTH
    assert "Profondeur de délégation dépassée" in result.content


def test_le_prompt_du_projet_precede_le_persona():
    run_turn = fake_turn([Token(text="ok"), Done()])
    outil = DelegateTool("h", "m", tools="gateway", run_turn=run_turn,
                         system_prompt=lambda: "Prompt du projet")

    outil.run(task="analyse", persona="relectrice")

    system = run_turn.calls[0]["messages"][0]
    assert system["role"] == "system"
    assert system["content"].startswith("Prompt du projet")
    assert "relectrice" in system["content"]


def test_le_prompt_du_projet_est_relu_a_chaque_delegation():
    run_turn = fake_turn([Token(text="ok"), Done()])
    prompts = iter(["v1", "v2"])
    outil = DelegateTool("h", "m", tools="gateway", run_turn=run_turn,
                         system_prompt=lambda: next(prompts))

    outil.run(task="a")
    outil.run(task="b")

    assert [c["messages"][0]["content"] for c in run_turn.calls] == ["v1", "v2"]


def test_un_sous_agent_ne_redelegue_pas():
    assert MAX_DELEGATION_DEPTH == 1


def fake_clock(monkeypatch, times):
    clock = itertools.chain(times, itertools.repeat(times[-1]))
    monkeypatch.setattr(delegate_tool.time, "monotonic", lambda: next(clock))


def test_apres_l_echeance_le_sous_agent_est_arrete_avec_sa_reponse_partielle(monkeypatch):
    closed = []

    def sub_agent(host, model, messages, tools):
        try:
            yield Token(text="début")
            yield Token(text=" jamais lu")
        finally:
            closed.append(True)

    # départ à 0 ; le premier morceau arrive après l'échéance (110 - 5 s)
    fake_clock(monkeypatch, [0.0, 200.0])
    result = DelegateTool("h", "m", tools="gateway", run_turn=sub_agent).run(task="long")

    assert not result.ok
    assert "délai" in result.content
    assert "début" in result.content and "jamais lu" not in result.content
    assert closed == [True]  # le générateur est refermé : plus rien en arrière-plan


def test_apres_l_echeance_aucun_outil_ni_confirmation(monkeypatch):
    class Gateway:
        def __init__(self):
            self.calls = []

        def describe_all(self):
            return []

        def call(self, name, /, **kwargs):
            self.calls.append(name)
            return ToolResult(ok=True, content="écrit")

    seen = []

    def sub_agent(host, model, messages, tools):
        seen.append(tools.call("write_file", path="x", content="y"))
        yield Token(text="fini")
        yield Done()

    # départ à 0, l'appel d'outil arrive à 200 s, après l'échéance
    fake_clock(monkeypatch, [0.0, 200.0])
    gateway = Gateway()
    DelegateTool("h", "m", tools=gateway, run_turn=sub_agent).run(task="écris")

    assert gateway.calls == []
    assert not seen[0].ok and "non exécuté" in seen[0].content


def test_le_delai_tient_dans_celui_de_la_passerelle():
    from sensai.execution.tool_policy import ToolPreferences

    assert DelegateTool.timeout_s <= ToolPreferences().tool_timeout_s
    assert delegate_tool.STOP_MARGIN_S < DelegateTool.timeout_s


def test_delegate_task_n_est_pas_propose_au_sous_agent():
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
    """Fausse passerelle qui propose tous les outils du projet et note les appels."""

    names = ("read_file", "search_codebase", "recall_facts", "write_file", "run_code",
             "web_search", "delegate_task", "team_task")

    def __init__(self):
        self.calls = []

    def describe_all(self):
        return [{"name": n} for n in self.names]

    def call(self, name, /, **kwargs):
        self.calls.append(name)
        return ToolResult(ok=True, content="fait")


def _seen_tools(role):
    seen = []

    def sub_agent(host, model, messages, tools):
        seen.extend(d["name"] for d in tools.describe_all())
        seen.append(("system", messages[0]["content"]))
        yield Token(text="ok")
        yield Done()

    DelegateTool("h", "m", tools=_Gateway(), run_turn=sub_agent).run(task="x", role=role)
    return seen


def test_l_explorateur_et_le_relecteur_ne_voient_aucun_outil_d_ecriture():
    for role in ("explorateur", "relecteur"):
        names = [s for s in _seen_tools(role) if isinstance(s, str)]
        assert "read_file" in names
        assert not {"write_file", "run_code", "delegate_task", "team_task"} & set(names)


def test_le_developpeur_peut_ecrire_mais_pas_deleguer():
    names = [s for s in _seen_tools("developpeur") if isinstance(s, str)]
    assert {"write_file", "run_code", "read_file"} <= set(names)
    assert not {"delegate_task", "team_task"} & set(names)


def test_le_role_donne_ses_consignes_au_sous_agent():
    system = dict(s for s in _seen_tools("relecteur") if isinstance(s, tuple))["system"]
    assert system == ROLES["relecteur"].prompt


def test_un_outil_hors_du_role_est_refuse_sans_etre_execute():
    gateway = _Gateway()
    seen = []

    def sub_agent(host, model, messages, tools):
        seen.append(tools.call("write_file", path="a", content="b"))
        yield Token(text="ok")
        yield Done()

    DelegateTool("h", "m", tools=gateway, run_turn=sub_agent).run(task="x", role="explorateur")

    assert gateway.calls == []
    assert not seen[0].ok and "non autorisé" in seen[0].content


def test_un_role_inconnu_est_refuse():
    result = DelegateTool("h", "m", tools=_Gateway(), run_turn=fake_turn([])).run(
        task="x", role="pirate")
    assert not result.ok and "Rôle inconnu" in result.content


def test_un_sous_agent_qui_tente_de_deleguer_recoit_un_refus_explicite():
    seen = []

    def sub_agent(host, model, messages, tools):
        seen.append(tools.call("team_task", task="x"))
        yield Token(text="ok")
        yield Done()

    DelegateTool("h", "m", tools=_Gateway(), run_turn=sub_agent).run(task="x")

    assert not seen[0].ok and "ne redélègue pas" in seen[0].content
