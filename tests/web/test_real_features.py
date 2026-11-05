"""
Ce qui était simulé dans le web et vient du vrai serveur depuis le 2026-10-29 :
consommation de tokens (M2), document d'état (M4), étapes des sous-agents (A2),
few-shot (A7), évaluation à la demande (EV1) et tâches planifiées (X5).
"""
import json

from sensai.core.events import Done, Token, ToolCall, ToolReturn
from sensai.core.tools import ToolResult
from sensai.web.runtime import Handoffs, _AnnouncedDelegate

STATE = ("call", "update_state", {"section": "Décisions", "action": "append",
                                  "content": "- On garde SQLite."})


def _approve(env, session_id):
    def on_event(event):
        if event["type"] == "confirm_request":
            env.post(f"/api/sessions/{session_id}/confirm",
                     {"confirm_id": event["confirm_id"], "approved": True})
    return on_event


def test_chaque_tour_annonce_sa_consommation_estimee(env):
    events = env.stream(env.session(), "Bonjour", keep_usage=True)
    usage = events[0]
    assert usage["type"] == "usage" and usage["estimated"] is True
    assert 0 < usage["used"] < usage["budget"] < usage["num_ctx"]


def test_une_section_modifiee_part_au_panneau_artefact(env):
    env.script.steps = [STATE, Token("Noté."), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Note la décision", on_event=_approve(env, session_id))
    patches = [e for e in events if e["type"] == "artifact_patch"]
    assert patches and patches[0]["section"] == "Décisions"
    assert "On garde SQLite." in patches[0]["markdown"]
    # La route le donne aussi, pour l'affichage au chargement de la page.
    assert "On garde SQLite." in env.get("/api/state").json()["bodies"]["Décisions"]


def test_les_outils_d_un_sous_agent_sont_publies_avec_son_role():
    sent = []

    class Outils:
        def call(self, name, **args):
            return ToolResult(ok=True, content="Lancer les tests avec pytest -q.")

        def describe(self):
            return []

    def sous_agent(host, model, messages, tools):
        yield ToolCall(id="s1", name="read_file", arguments={"path": "notes.md"})
        result = tools.call("read_file", path="notes.md")
        yield ToolReturn(id="s1", name="read_file", ok=result.ok, content=result.content)
        yield Token("Lu.")
        yield Done("final_answer")

    handoffs = Handoffs(sent.append)
    delegate = _AnnouncedDelegate("h", "m", Outils(), run_turn=sous_agent, handoffs=handoffs)
    assert delegate.run(task="Lis notes.md", role="explorateur").ok
    assert [e["type"] for e in sent] == ["agent_handoff", "subagent_step"]
    step = sent[1]
    assert step["agent"] == "explorateur" and step["tool"] == "read_file"
    assert step["ok"] is True and "pytest" in step["content"]


def test_le_few_shot_le_plus_proche_accompagne_la_question(env, tmp_path):
    examples = tmp_path / "exemples.jsonl"
    examples.write_text(json.dumps({"id": "t", "question": "Comment lancer les tests ?",
                                    "answer": "Avec pytest -q."}) + "\n", encoding="utf-8")
    env.runtime.settings.update(fewshot_examples=str(examples), fewshot_min_score=0.3)
    events = env.stream(env.session(), "Comment lancer les tests ?")
    assert any(e["type"] == "fewshot" for e in events)
    assert "Avec pytest -q." in env.script.calls[-1][-1]["content"]


def test_un_fichier_d_exemples_absent_devient_un_avertissement(env):
    env.runtime.settings.update(fewshot_examples="nexiste/pas.jsonl")
    env.stream(env.session(), "Bonjour")
    assert any("few-shot" in n for n in env.get("/api/config").json()["notices"])


def test_evaluer_la_derniere_reponse(env):
    session_id = env.session()
    env.stream(session_id, "Comment lancer les tests ?")
    judged = []

    def fake_judge(host, model, num_ctx=None):
        def judge(messages):
            judged.append(messages)
            return json.dumps({"relevance": 4, "coherence": 5, "claims": []})
        return judge

    env.runtime._judge_factory = fake_judge
    response = env.post(f"/api/sessions/{session_id}/evaluate")
    assert response.status_code == 200, response.text
    scores = response.json()["scores"]
    assert scores["relevance"] == 4 and scores["coherence"] == 5
    assert "Comment lancer les tests ?" in json.dumps(judged[0], ensure_ascii=False)


def test_rien_a_evaluer(env):
    response = env.post(f"/api/sessions/{env.session()}/evaluate")
    assert response.status_code == 400 and response.json()["code"] == "NOTHING_TO_EVALUATE"


def test_un_juge_illisible_est_une_erreur_claire(env):
    session_id = env.session()
    env.stream(session_id, "Bonjour")
    env.runtime._judge_factory = lambda host, model, num_ctx=None: (lambda messages: "pas du json")
    response = env.post(f"/api/sessions/{session_id}/evaluate")
    assert response.status_code == 502 and response.json()["code"] == "EVALUATION_FAILED"


def test_taches_planifiees_ajout_liste_pause_suppression(env):
    created = env.post("/api/schedule/tasks", {"id": "veille", "prompt": "Résume les TODO",
                                               "every": "2h"})
    assert created.status_code == 201, created.text
    assert created.json()["interval_s"] == 7200 and created.json()["next_due"] is None
    assert [t["id"] for t in env.get("/api/schedule/tasks").json()] == ["veille"]
    assert env.post("/api/schedule/tasks/veille/enabled", {"enabled": False}).status_code == 204
    assert env.get("/api/schedule/tasks").json()[0]["enabled"] is False
    # Le fichier est celui que lit `sensai-schedule`.
    assert "veille" in env.runtime.tasks.path.read_text(encoding="utf-8")
    assert env.post("/api/schedule/tasks/veille/remove").status_code == 204
    assert env.get("/api/schedule/tasks").json() == []
    assert env.post("/api/schedule/tasks/veille/remove").status_code == 404


def test_une_tache_mal_ecrite_est_refusee(env):
    for body in ({"id": "a b", "prompt": "x", "every": "1h"},
                 {"id": "ok", "prompt": "  ", "every": "1h"},
                 {"id": "ok", "prompt": "x", "every": "jamais"}):
        response = env.post("/api/schedule/tasks", body)
        assert response.status_code == 400 and response.json()["code"] == "INVALID_TASK", body
    env.post("/api/schedule/tasks", {"id": "ok", "prompt": "x", "every": "1h"})
    assert env.post("/api/schedule/tasks", {"id": "ok", "prompt": "y", "every": "1h"}
                    ).status_code == 400


def test_les_exemples_few_shot_sont_lisibles_par_l_interface(env, tmp_path):
    """A7 : la page Prompts montre le fichier, le seuil et les questions des exemples."""
    examples = tmp_path / "exemples.jsonl"
    examples.write_text(json.dumps({"id": "t", "question": "Comment lancer les tests ?",
                                    "answer": "Avec pytest -q."}) + "\n", encoding="utf-8")
    assert env.get("/api/fewshot").json()["configured"] is False
    env.runtime.settings.update(fewshot_examples=str(examples), fewshot_min_score=0.3)
    info = env.get("/api/fewshot").json()
    assert info["configured"] and info["questions"] == ["Comment lancer les tests ?"]
    assert info["min_score"] == 0.3 and info["error"] is None


def test_l_heure_du_prompt_est_figee_par_conversation(env, monkeypatch):
    """L'heure du premier tour reste dans le prompt système de la conversation : une
    heure qui changerait à chaque tour obligerait Ollama à relire toute la conversation."""
    from datetime import datetime, timedelta, timezone

    from sensai.web import runtime as runtime_module

    clock = iter([datetime(2026, 11, 1, 9, 5, tzinfo=timezone(timedelta(hours=1))),
                  datetime(2026, 11, 1, 9, 40, tzinfo=timezone(timedelta(hours=1)))])
    monkeypatch.setattr(runtime_module, "local_datetime", lambda: next(clock))
    rt = env.runtime
    first = rt.system_prompt(resumed=False, started=rt.started_at("s1"))
    assert "09:05" in first
    assert rt.system_prompt(resumed=True, started=rt.started_at("s1")).count("09:05") == 1
    assert "09:40" in rt.system_prompt(resumed=False, started=rt.started_at("s2"))


def test_les_preferences_arrivent_en_dernier_dans_le_prompt(env):
    """Essai réel du 2026-11-01 : « réponds toujours en anglais » ignoré quand le profil
    était suivi du document d'état et des faits, en français."""
    rt = env.runtime
    rt.profile.preferences.append("Réponds toujours en anglais.")
    prompt = rt.system_prompt(resumed=False)
    assert prompt.rstrip().endswith("- Réponds toujours en anglais.")
    assert prompt.index("Pour cette session, tu es") < prompt.index("## Profil de l'utilisateur")


def test_les_resultats_de_web_search_sont_relus_pour_l_onglet_sources():
    """Audit du 2026-11-01 (US-T3-1) : `web_results` n'était jamais envoyé. Le motif doit
    suivre le format de web_search_tool._format ; ce test casse si l'un des deux change."""
    from sensai.execution.sandbox.browser_sandbox import SearchOutcome, SearchResult
    from sensai.tools.web_search_tool import WebSearchTool
    from sensai.web.runtime import _WEB_RESULT

    text = WebSearchTool._format(SearchOutcome(ok=True, query="python", results=[
        SearchResult(title="Python 3.15.2", url="https://www.python.org/", snippet="Sortie"),
        SearchResult(title="PyPI", url="https://pypi.org/", snippet=""),
    ]))
    assert _WEB_RESULT.findall(text) == [("Python 3.15.2", "https://www.python.org/"),
                                         ("PyPI", "https://pypi.org/")]
