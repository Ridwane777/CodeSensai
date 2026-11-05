"""
Questions de l'agent dans le navigateur (X4, ADR-0046) : le broker seul, puis
le parcours complet à travers le vrai serveur.

Le test qui compte : `test_la_reponse_du_formulaire_revient_au_modele` (critère
« l'agent reprend la main en utilisant les valeurs saisies », US-X4-1).
"""
import threading

from sensai.core.events import Done, Token
from sensai.tools.ask_user_tool import parse_question
from sensai.web.questions import WebQuestionBroker
from tests.web.conftest import types

FIELDS = [
    {"id": "style", "kind": "choice", "label": "Style", "options": ["pytest", "unittest"]},
    {"id": "nom", "kind": "text", "label": "Nom"},
]
ASK = ("call", "ask_user", {"title": "Quel style de tests ?", "fields": FIELDS})
GOOD = {"style": "pytest", "nom": "test_outils"}

# --- Le broker seul ------------------------------------------------------------------


def _ask_in_thread(broker):
    result = {}
    thread = threading.Thread(
        target=lambda: result.setdefault("v", broker.ask(parse_question("?", FIELDS))))
    thread.start()
    return thread, result


def test_le_broker_rend_la_reponse_valide():
    sent = []
    broker = WebQuestionBroker(sent.append, timeout_s=5)
    thread, result = _ask_in_thread(broker)
    while not sent:
        pass
    question_id = sent[0]["question_id"]
    assert broker.resolve(question_id, {"style": "nose", "nom": "x"}) == "style : choix inconnu"
    assert broker.resolve(question_id, GOOD) == "ok"
    thread.join(5)
    assert result["v"] == GOOD
    assert broker.resolve(question_id, GOOD) == "unknown"  # déjà répondu


def test_sans_reponse_a_temps_le_broker_rend_none():
    broker = WebQuestionBroker(lambda e: None, timeout_s=0.2)
    assert broker.ask(parse_question("?", FIELDS)) is None


def test_un_broker_ferme_ne_pose_plus_de_question():
    sent = []
    broker = WebQuestionBroker(sent.append, timeout_s=5)
    broker.close()
    assert broker.ask(parse_question("?", FIELDS)) is None and sent == []


def test_un_emit_en_panne_c_est_pas_de_reponse():
    def broken(event):
        raise RuntimeError("flux fermé")
    assert WebQuestionBroker(broken, timeout_s=5).ask(parse_question("?", FIELDS)) is None


# --- À travers le serveur --------------------------------------------------------------


def _answer(env, session_id, values, expect=204):
    def on_event(event):
        if event["type"] == "question":
            assert event["title"] == "Quel style de tests ?"
            assert [f["id"] for f in event["fields"]] == ["style", "nom"]
            response = env.post(f"/api/sessions/{session_id}/answer",
                                {"question_id": event["question_id"], "values": values})
            assert response.status_code == expect, response.text
    return on_event


def test_la_reponse_du_formulaire_revient_au_modele(env):
    env.script.steps = [ASK, Token("Compris."), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Écris des tests", on_event=_answer(env, session_id, GOOD))
    assert types(events) == ["tool_call", "question", "tool_return", "token", "done"]
    assert events[2]["ok"] is True
    assert '"style": "pytest"' in events[2]["content"]
    assert '"nom": "test_outils"' in events[2]["content"]


def test_une_reponse_invalide_est_refusee_et_la_question_reste_ouverte(env):
    env.script.steps = [ASK, Done("final_answer")]
    session_id = env.session()

    def on_event(event):
        if event["type"] == "question":
            bad = env.post(f"/api/sessions/{session_id}/answer",
                           {"question_id": event["question_id"],
                            "values": {"style": "nose", "nom": "x"}})
            assert bad.status_code == 400 and bad.json()["code"] == "INVALID_ANSWER"
            good = env.post(f"/api/sessions/{session_id}/answer",
                            {"question_id": event["question_id"], "values": GOOD})
            assert good.status_code == 204

    events = env.stream(session_id, "Écris des tests", on_event=on_event)
    assert events[2]["type"] == "tool_return" and events[2]["ok"] is True


def test_question_inconnue(env):
    session_id = env.session()
    response = env.post(f"/api/sessions/{session_id}/answer",
                        {"question_id": "question_x", "values": {}})
    assert response.status_code == 404 and response.json()["code"] == "QUESTION_NOT_FOUND"


def test_interrompre_pendant_une_question(env):
    env.script.steps = [ASK, Token("Jamais dit."), Done("final_answer")]
    session_id = env.session()

    def on_event(event):
        if event["type"] == "question":
            env.post(f"/api/sessions/{session_id}/interrupt")

    events = env.stream(session_id, "Écris des tests", on_event=on_event)
    assert events[-1] == {"type": "done", "reason": "interrupted"}
    assert "Jamais dit." not in [e.get("text") for e in events]


def test_un_secret_tape_dans_le_formulaire_est_masque_avant_le_modele(env):
    env.script.steps = [ASK, Done("final_answer")]
    session_id = env.session()
    secret = "AKIAIOSFODNN7EXAMPLE"
    events = env.stream(session_id, "Écris des tests",
                        on_event=_answer(env, session_id, {"style": "pytest", "nom": secret}))
    assert secret not in events[2]["content"]
