"""
Relais entre agents dans le web (X1, A2) : le serveur publie un `agent_handoff`
réel quand un sous-agent prend la main, et quand l'agent principal la reprend.

Les sous-agents tournent pour de vrai avec un Ollama injoignable : ils échouent
vite, ce qui suffit à vérifier QUI a eu la main et dans quel ordre.
"""
from sensai.core.events import Done
from tests.web.conftest import types

DELEGATE = ("call", "delegate_task", {"task": "Lis le module", "role": "explorateur"})
TEAM = ("call", "team_task", {"task": "Corrige le bug"})


def _confirm(env, session_id, approved=True):
    def on_event(event):
        if event["type"] == "confirm_request":
            env.post(f"/api/sessions/{session_id}/confirm",
                     {"confirm_id": event["confirm_id"], "approved": approved})
    return on_event


def _handoffs(events):
    return [(e["from"], e["to"]) for e in events if e["type"] == "agent_handoff"]


def test_une_delegation_annonce_l_aller_et_le_retour(env):
    env.script.steps = [DELEGATE, Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Délègue", on_event=_confirm(env, session_id))
    assert _handoffs(events) == [("main", "explorateur"), ("explorateur", "main")]
    # Le relais suit la confirmation et précède le résultat de l'outil.
    order = types(events)
    assert order.index("confirm_request") < order.index("agent_handoff")
    assert max(i for i, t in enumerate(order) if t == "agent_handoff") < order.index("tool_return")


def test_une_delegation_refusee_n_annonce_aucun_relais(env):
    env.script.steps = [DELEGATE, Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Délègue", on_event=_confirm(env, session_id, False))
    assert _handoffs(events) == []


def test_sans_role_c_est_un_sous_agent(env):
    env.script.steps = [("call", "delegate_task", {"task": "Résume"}), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Délègue", on_event=_confirm(env, session_id))
    assert _handoffs(events) == [("main", "sous-agent"), ("sous-agent", "main")]


def test_l_equipe_annonce_chaque_relais_puis_le_retour(env):
    env.script.steps = [TEAM, Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Équipe", on_event=_confirm(env, session_id))
    assert _handoffs(events) == [
        ("main", "explorateur"),
        ("explorateur", "developpeur"),
        ("developpeur", "relecteur"),
        ("relecteur", "main"),
    ]
