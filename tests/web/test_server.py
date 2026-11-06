"""
Le serveur web réel (ADR-0035) : API, flux, confirmation, interruption, mémoires.

Chaque bloc renvoie aux user stories du serveur (docs/architecture/web-api.md)
et aux décisions ADR-0022 à 0024.

Les tests qui comptent le plus :
- `test_seul_oui_a_temps_autorise_l_ecriture` et ses voisins : une action
  risquée ne s'exécute qu'avec un « oui » explicite et à temps (ADR-0015).
- `test_toute_route_demande_le_jeton` : l'API ne s'ouvre jamais sans jeton (ADR-0023).
- `test_meme_agent_que_le_cli` : le web propose les mêmes outils que le CLI.
"""
import threading
import time

import pytest
import requests

from sensai.core.events import Done, Error, Thought, Token
from sensai.knowledge.memory import SESSIONS_FILE, SessionStore
from tests.web.conftest import TOKEN, types

# --- Accès (ADR-0023) -------------------------------------------------------------

ROUTES = [
    ("get", "/api/config"),
    ("get", "/api/sessions"),
    ("post", "/api/sessions"),
    ("get", "/api/sessions/abc"),
    ("post", "/api/sessions/abc/messages"),
    ("post", "/api/sessions/abc/confirm"),
    ("post", "/api/sessions/abc/answer"),
    ("post", "/api/sessions/abc/interrupt"),
    ("post", "/api/sessions/abc/fork"),
    ("get", "/api/sessions/abc/export"),
    ("post", "/api/sessions/abc/delete"),
    ("post", "/api/sessions/abc/share"),
    ("post", "/api/shares/abc/revoke"),
    ("get", "/api/profile"),
    ("post", "/api/profile/preferences"),
    ("post", "/api/profile/forget"),
    ("get", "/api/facts"),
    ("get", "/api/fewshot"),
    ("post", "/api/facts/forget"),
    ("get", "/api/state"),
    ("get", "/api/personas"),
    ("get", "/api/sessions/abc/persona"),
    ("post", "/api/sessions/abc/persona"),
    ("get", "/api/prompts"),
    ("get", "/api/prompts/system/v1"),
    ("get", "/api/prompts/system/diff"),
    ("get", "/api/sessions/abc/prompt-trial"),
    ("post", "/api/sessions/abc/prompt-trial"),
]


def test_sante_sans_jeton(env):
    assert requests.get(f"{env.base}/api/health", timeout=5).json() == {"status": "ok"}


@pytest.mark.parametrize("method, path", ROUTES)
@pytest.mark.parametrize("header", [None, "Bearer faux", "Basic " + TOKEN, TOKEN, "Bearer "])
def test_toute_route_demande_le_jeton(env, method, path, header):
    headers = {"Authorization": header} if header else {}
    response = getattr(requests, method)(env.base + path, headers=headers, json={}, timeout=5)
    assert response.status_code == 401
    assert response.json() == {"error": "Authentification requise", "code": "UNAUTHORIZED",
                               "details": ""}


def test_la_configuration_ne_devoile_ni_adresse_ni_chemin(env):
    config = env.get("/api/config").json()
    text = str(config)
    assert config["model"] == "faux-modele" and config["project"] == "projet"
    assert "127.0.0.1" not in text and str(env.project) not in text and TOKEN not in text


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_pas_de_documentation_publique(env, path):
    assert requests.get(env.base + path, timeout=5).status_code == 404


def test_cors_ferme(env):
    def preflight(origin):
        return requests.options(f"{env.base}/api/sessions", timeout=5, headers={
            "Origin": origin, "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in preflight("http://evil.example").headers
    allowed = preflight("http://allowed.example").headers
    assert allowed["access-control-allow-origin"] == "http://allowed.example"


# --- Sessions (M1, US-WEB-6) ------------------------------------------------------------


def test_une_session_web_est_une_session_du_cli(env):
    session_id = env.session()
    env.stream(session_id, "Bonjour")
    store = SessionStore(env.runtime.data_dir / SESSIONS_FILE)
    assert store.load(session_id) == [{"role": "user", "content": "Bonjour"},
                                      {"role": "assistant", "content": "Bonjour."}]
    listed = env.get("/api/sessions").json()
    assert [s["session_id"] for s in listed] == [session_id]
    assert listed[0]["message_count"] == 2 and listed[0]["title"] == "Bonjour"


def test_une_session_vide_n_est_pas_listee(env):
    env.session()
    assert env.get("/api/sessions").json() == []


def test_session_inconnue(env):
    response = env.get("/api/sessions/inconnue")
    assert response.status_code == 404
    assert response.json()["code"] == "SESSION_NOT_FOUND"
    assert env.post("/api/sessions/inconnue/messages", {"content": "x"}).status_code == 404


def test_l_historique_est_envoye_au_modele(env):
    session_id = env.session()
    env.stream(session_id, "Premier")
    env.stream(session_id, "Second")
    messages = env.script.calls[-1]
    assert messages[0]["role"] == "system" and "Conversation reprise." in messages[0]["content"]
    assert [m["content"] for m in messages[1:]] == ["Premier", "Bonjour.", "Second"]


# --- Le flux d'un tour (ADR-0022) -------------------------------------------------------


def test_le_flux_finit_par_done(env):
    env.script.steps = [Thought("Je réfléchis."), Token("Bon"), Token("jour."),
                        Done("final_answer")]
    events = env.stream(env.session(), "Salut")
    assert types(events) == ["thought", "token", "token", "done"]
    assert events[-1] == {"type": "done", "reason": "final_answer"}


def test_appel_d_outil_de_lecture(env):
    env.script.steps = [("call", "read_file", {"path": "notes.md"}), Token("Lu."),
                        Done("final_answer")]
    events = env.stream(env.session(), "Lis notes.md")
    call, result = events[0], events[1]
    assert call == {"type": "tool_call", "id": "c1", "name": "read_file",
                    "arguments": {"path": "notes.md"}}
    assert result["type"] == "tool_return" and result["ok"] and "pytest -q" in result["content"]


def test_une_erreur_du_modele_n_entre_pas_dans_l_historique(env):
    env.script.steps = [Error("Ollama injoignable"), Done("error")]
    session_id = env.session()
    events = env.stream(session_id, "Bonjour")
    assert types(events) == ["error", "done"]
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []


def test_un_bug_du_coeur_ferme_le_flux_proprement(env):
    env.script.raise_error = True
    events = env.stream(env.session(), "Bonjour")
    assert events == [{"type": "error", "message": "Erreur interne du serveur."},
                      {"type": "done", "reason": "error"}]


@pytest.mark.parametrize("body, status, code", [
    ({"content": "   "}, 400, "EMPTY_MESSAGE"),
    ({"content": "x" * 20_001}, 413, "MESSAGE_TOO_LONG"),
    ({}, 400, "INVALID_REQUEST"),
    ({"content": 42}, 400, "INVALID_REQUEST"),
])
def test_messages_refuses(env, body, status, code):
    response = env.post(f"/api/sessions/{env.session()}/messages", body)
    assert response.status_code == status and response.json()["code"] == code


def test_json_invalide(env):
    response = requests.post(f"{env.base}/api/sessions/{env.session()}/messages",
                             data="{pas du json", timeout=5,
                             headers={**env.headers(), "Content-Type": "application/json"})
    assert response.status_code == 400 and response.json()["code"] == "INVALID_REQUEST"


def test_un_seul_tour_a_la_fois(env):
    env.script.pause = 0.3
    session_id = env.session()
    started = threading.Event()
    statuses = []

    def second(event):
        if not started.is_set():
            started.set()
            statuses.append(env.post(f"/api/sessions/{session_id}/messages",
                                     {"content": "encore"}).status_code)

    env.stream(session_id, "Bonjour", on_event=second)
    assert statuses == [409]
    assert types(env.stream(session_id, "Ensuite"))[-1] == "done", "la session est libérée"


def test_deux_sessions_en_parallele(env):
    env.script.pause = 0.1
    a, b = env.session(), env.session()
    results = {}
    threads = [threading.Thread(target=lambda s=s: results.__setitem__(s, env.stream(s, s)))
               for s in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for s in (a, b):
        assert types(results[s])[-1] == "done"
        assert env.get(f"/api/sessions/{s}").json()["messages"][0]["content"] == s


# --- Confirmation (A3, ADR-0015) --------------------------------------------------------

WRITE = ("call", "write_file", {"path": "nouveau.txt", "content": "salut\n"})


def answer(env, session_id, approved):
    def on_event(event):
        if event["type"] == "confirm_request":
            assert event["confirm_id"] == event["id"] and event["tool"] == "write_file"
            assert event["risk"] == "write" and event["arguments"]["path"] == "nouveau.txt"
            assert "nouveau.txt" in event["summary"]
            status = env.post(f"/api/sessions/{session_id}/confirm",
                              {"confirm_id": event["confirm_id"], "approved": approved})
            assert status.status_code == 204
    return on_event


def test_seul_oui_a_temps_autorise_l_ecriture(env):
    env.script.steps = [WRITE, Token("Écrit."), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Écris", on_event=answer(env, session_id, True))
    assert types(events) == ["tool_call", "confirm_request", "tool_return", "token", "done"]
    assert events[2]["ok"] is True
    assert (env.project / "nouveau.txt").read_text() == "salut\n"


def test_non_refuse_l_ecriture(env):
    env.script.steps = [WRITE, Token("Refusé."), Done("final_answer")]
    session_id = env.session()
    events = env.stream(session_id, "Écris", on_event=answer(env, session_id, False))
    assert events[2]["type"] == "tool_return" and events[2]["ok"] is False
    assert not (env.project / "nouveau.txt").exists()


@pytest.mark.parametrize("value", ["true", 1, "yes"])
def test_seul_le_booleen_vrai_compte(env, value):
    env.script.steps = [WRITE, Done("final_answer")]
    session_id = env.session()

    def on_event(event):
        if event["type"] == "confirm_request":
            response = env.post(f"/api/sessions/{session_id}/confirm",
                                {"confirm_id": event["confirm_id"], "approved": value})
            # pydantic accepterait "true", 1 ou "yes" comme vrai : seul le
            # booléen JSON true doit compter, le reste est refusé à l'entrée.
            assert response.status_code == 400
            env.post(f"/api/sessions/{session_id}/confirm",
                     {"confirm_id": event["confirm_id"], "approved": False})

    env.stream(session_id, "Écris", on_event=on_event)
    assert not (env.project / "nouveau.txt").exists()


def test_sans_reponse_a_temps_c_est_un_refus(make_env):
    env = make_env(confirm_timeout_s=0.5)
    env.script.steps = [WRITE, Done("final_answer")]
    session_id = env.session()
    seen = []

    def late(event):
        if event["type"] == "confirm_request":
            seen.append(event["confirm_id"])
        if event["type"] == "tool_return":
            response = env.post(f"/api/sessions/{session_id}/confirm",
                                {"confirm_id": seen[0], "approved": True})
            assert response.status_code == 404, "une réponse tardive est sans effet"

    events = env.stream(session_id, "Écris", on_event=late)
    assert next(e for e in events if e["type"] == "tool_return")["ok"] is False
    assert not (env.project / "nouveau.txt").exists()


def test_confirmation_inconnue_ou_deja_donnee(env):
    env.script.steps = [WRITE, Done("final_answer")]
    session_id = env.session()
    assert env.post(f"/api/sessions/{session_id}/confirm",
                    {"confirm_id": "inconnu", "approved": True}).status_code == 404
    codes = []

    def twice(event):
        if event["type"] == "confirm_request":
            for approved in (False, True):
                codes.append(env.post(f"/api/sessions/{session_id}/confirm",
                                      {"confirm_id": event["confirm_id"],
                                       "approved": approved}).status_code)

    env.stream(session_id, "Écris", on_event=twice)
    assert codes == [204, 404], "la première réponse l'emporte"
    assert not (env.project / "nouveau.txt").exists()


# --- Interruption et déconnexion (X2, US-WEB-7) ----------------------------------------


def test_interrompre_pendant_une_confirmation(env):
    env.script.steps = [WRITE, Token("après"), Done("final_answer")]
    session_id = env.session()

    def stop(event):
        if event["type"] == "confirm_request":
            assert env.post(f"/api/sessions/{session_id}/interrupt").status_code == 204

    events = env.stream(session_id, "Écris", on_event=stop)
    assert events[-1] == {"type": "done", "reason": "interrupted"}
    assert "token" not in types(events)
    assert not (env.project / "nouveau.txt").exists()
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []


def test_interrompre_sans_tour_est_sans_effet(env):
    assert env.post(f"/api/sessions/{env.session()}/interrupt").status_code == 204


def test_onglet_ferme_pendant_une_confirmation(env):
    env.script.steps = [WRITE, Done("final_answer")]
    session_id = env.session()
    with requests.post(f"{env.base}/api/sessions/{session_id}/messages",
                       json={"content": "Écris"}, headers=env.headers(), stream=True,
                       timeout=10) as response:
        for line in response.iter_lines(decode_unicode=True):
            if line and "confirm_request" in line:
                break  # on ferme sans répondre
    for _ in range(100):  # la session se libère : un nouveau message est accepté
        env.script.steps = [Token("ok"), Done("final_answer")]
        reply = env.post(f"/api/sessions/{session_id}/messages", {"content": "encore"})
        if reply.status_code == 200:
            break
        time.sleep(0.05)
    assert reply.status_code == 200
    assert not (env.project / "nouveau.txt").exists()


# --- Garde-fous, commandes, cache, RAG ---------------------------------------------------


def test_une_entree_bloquee_ne_part_pas_au_modele(make_env):
    env = make_env(blocklist=[{"name": "interdit", "pattern": "mot-interdit",
                               "why": "sujet refusé"}])
    session_id = env.session()
    events = env.stream(session_id, "parle du mot-interdit")
    assert types(events) == ["guardrail", "done"]
    assert events[0]["kind"] == "unsafe" and events[1]["reason"] == "blocked"
    assert env.script.calls == []
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []


def test_les_commandes_du_chat_marchent_comme_dans_le_cli(env):
    session_id = env.session()
    events = env.stream(session_id, "/state")
    assert types(events) == ["token", "done"] and events[1]["reason"] == "command"
    terminal = env.stream(session_id, "/schedule list")
    assert "terminal" in terminal[0]["text"]
    env.stream(session_id, "/remember réponds en français")
    assert "réponds en français" in env.get("/api/profile").json()["preferences"]
    assert env.script.calls == []
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []


def test_le_cache_repond_sans_rappeler_le_modele(make_env):
    env = make_env(cache=True)
    session_id = env.session()
    question = "Comment lancer les tests du projet ?"
    env.stream(session_id, question)
    events = env.stream(session_id, question)
    assert types(events) == ["cache_hit", "token", "done"]
    assert events[0]["question"] == question and events[0]["similarity"] >= 0.99
    assert events[1]["text"] == "Bonjour."
    assert len(env.script.calls) == 1
    env.stream(session_id, question, skip_cache=True)
    assert len(env.script.calls) == 2, "/again redemande au modèle"


def test_une_reponse_qui_a_liste_les_fichiers_va_en_cache(make_env):
    """Répétition de la démo du 2026-11-06 : list_files (ADR-0059) ne fait que lire,
    mais n'étant pas dans les outils « cachables », la réponse n'était jamais gardée."""
    env = make_env(cache=True)
    env.script.steps = [("call", "list_files", {}), Token("pytest -q"), Done("final_answer")]
    session_id = env.session()
    question = "Comment lancer les tests du projet ?"
    env.stream(session_id, question)
    events = env.stream(env.session(), question)
    assert types(events)[0] == "cache_hit"
    assert len(env.script.calls) == 1


def test_les_sources_du_rag_sont_envoyees(make_env):
    env = make_env(rag=True)
    events = env.stream(env.session(), "Comment lancer les tests ?")
    sources = next(e for e in events if e["type"] == "rag_sources")["sources"]
    assert sources[0]["path"] == "notes.md" and sources[0]["lines"] == "1-2"
    assert "notes.md" in env.script.calls[0][-1]["content"], "les passages partent au modèle"


# --- Bifurcation, export, mémoires ------------------------------------------------------


def test_bifurcation(env):
    session_id = env.session()
    env.stream(session_id, "Premier")
    env.stream(session_id, "Second")
    branch = env.post(f"/api/sessions/{session_id}/fork", {"at_message": 2})
    assert branch.status_code == 201
    new_id = branch.json()["session_id"]
    assert new_id != session_id
    assert [m["content"] for m in env.get(f"/api/sessions/{new_id}").json()["messages"]] == [
        "Premier", "Bonjour."]
    assert env.post(f"/api/sessions/{session_id}/fork", {"at_message": 9}).status_code == 400
    assert env.post(f"/api/sessions/{session_id}/fork", {"at_message": -1}).status_code == 400


def test_supprimer_une_conversation(env):
    session_id = env.session()
    env.stream(session_id, "Bonjour")
    assert env.post(f"/api/sessions/{session_id}/delete").status_code == 204
    assert env.get(f"/api/sessions/{session_id}").status_code == 404
    assert session_id not in [s["session_id"] for s in env.get("/api/sessions").json()]
    assert env.post(f"/api/sessions/{session_id}/delete").status_code == 404


def test_pas_de_suppression_pendant_un_tour(env):
    env.script.pause = 0.3
    session_id = env.session()
    codes = []

    def on_event(event):
        if not codes:
            codes.append(env.post(f"/api/sessions/{session_id}/delete").status_code)

    env.stream(session_id, "Bonjour", on_event=on_event)
    assert codes == [409]
    assert env.get(f"/api/sessions/{session_id}").status_code == 200


def test_export_filtre_les_secrets(env):
    session_id = env.session()
    env.script.steps = [Token("Ta clé : sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"),
                        Done("final_answer")]
    env.stream(session_id, "password = hunter2-tres-secret")
    as_json = env.get(f"/api/sessions/{session_id}/export?format=json")
    text = str(as_json.json())
    assert "hunter2-tres-secret" not in text and "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in text
    assert "REDACTED" in text
    as_md = env.get(f"/api/sessions/{session_id}/export?format=md")
    assert as_md.headers["content-type"].startswith("text/markdown")
    assert "## Vous" in as_md.text and "hunter2-tres-secret" not in as_md.text
    assert env.get(f"/api/sessions/{session_id}/export?format=pdf").status_code == 400


def test_preferences_ajoutees_puis_oubliees_depuis_le_web(env):
    """US-WEB-6 : ajouter (vide ou doublon ignorés), effacer ; le fichier du profil suit,
    et la préférence entre dans le prompt du tour suivant."""
    add = lambda text: env.post("/api/profile/preferences", {"text": text})  # noqa: E731
    assert add("utilise pytest").json()["preferences"] == ["utilise pytest"]
    assert add("utilise pytest").json()["preferences"] == ["utilise pytest"]
    assert add("   ").json()["preferences"] == ["utilise pytest"]
    assert "utilise pytest" in env.runtime.profile_path.read_text(encoding="utf-8")
    env.stream(env.session(), "Bonjour")
    assert "utilise pytest" in env.script.calls[-1][0]["content"]
    assert env.post("/api/profile/forget").json()["preferences"] == []
    assert env.get("/api/profile").json()["preferences"] == []


def test_une_preference_trop_longue_est_refusee(env):
    response = env.post("/api/profile/preferences", {"text": "x" * 501})
    assert response.status_code == 400 and response.json()["code"] == "INVALID_REQUEST"


def test_oublier_les_faits_d_une_entite(env):
    """Essai du 2026-11-01 : les faits survivent à la suppression d'une conversation ;
    le web doit pouvoir les oublier."""
    env.runtime.facts.remember("mot_de_test", "mot", "zebre-violet")
    assert "mot_de_test" in env.get("/api/facts").json()["facts"]
    assert env.post("/api/facts/forget", {"entity": "mot_de_test"}).json() == {"removed": 1}
    assert "mot_de_test" not in env.get("/api/facts").json()["facts"]
    assert env.post("/api/facts/forget", {"entity": "mot_de_test"}).status_code == 404


def test_faits_et_document_d_etat(env):
    env.runtime.facts.remember("redis", "version", "8")
    assert env.get("/api/facts").json()["facts"]["redis"][0]["value"] == "8"
    state = env.get("/api/state").json()
    assert state["markdown"] == "" and "Fait" in state["sections"]


# --- L'interface servie, la parité avec le CLI, la purge (#65) --------------------------


def test_l_interface_est_servie_avec_l_api(make_env, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>CodeSensei</html>", encoding="utf-8")
    env = make_env(frontend_dir=dist)
    assert "CodeSensei" in requests.get(env.base + "/", timeout=5).text
    assert env.get("/api/config").status_code == 200


def test_sans_interface_construite_l_api_marche_seule(env):
    assert requests.get(env.base + "/", timeout=5).status_code == 404
    assert env.get("/api/config").status_code == 200


def test_meme_agent_que_le_cli(env):
    from sensai.registry import build_registry
    from sensai.tools.ask_user_tool import AskUserTool
    from sensai.tools.delegate_tool import DelegateTool
    from sensai.tools.fact_tools import RecallFactsTool, RememberFactTool
    from sensai.tools.rag_tool import RagTool
    from sensai.tools.schedule_task_tool import ScheduleTaskTool
    from sensai.tools.state_tool import UpdateStateTool
    from sensai.tools.team_tool import TeamTool

    cli = build_registry(env.settings["file_permissions"])
    for tool in (RagTool(), UpdateStateTool(env.runtime.state),
                 RememberFactTool(env.runtime.facts), RecallFactsTool(env.runtime.facts),
                 DelegateTool("h", "m", tools=None),
                 TeamTool(DelegateTool("h", "m", tools=None)), AskUserTool(None),
                 ScheduleTaskTool(env.runtime.data_dir)):
        cli.register(tool)
    env.runtime.rag_on = True
    web = env.runtime.make_gateway(lambda request: False)
    assert sorted(t["name"] for t in web.describe_all()) == sorted(
        t["name"] for t in cli.describe_all())


def test_les_vieilles_sessions_sont_purgees_au_demarrage(env):
    import sqlite3
    old = env.runtime.store.create(env.runtime.project)
    env.runtime.store.save(old, [{"role": "user", "content": "vieux"}])
    with sqlite3.connect(env.runtime.store.db_path) as conn:
        conn.execute("UPDATE sessions SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                     (old,))
    assert env.runtime.purge() == 1
    assert not env.runtime.store.exists(old)


def test_les_passages_du_rag_sont_filtres(make_env):
    """EV2, comme le CLI : pas de secret en clair dans les passages ajoutés à la question."""
    env = make_env(rag=True)
    (env.project / "reglages.py").write_text(
        '# comment lancer les tests\nAPI_KEY = "sk-abcdef1234567890abcdef"\n', encoding="utf-8")
    env.stream(env.session(), "Comment lancer les tests ?")
    sent = env.script.calls[0][-1]["content"]
    assert "reglages.py" in sent
    assert "sk-abcdef1234567890abcdef" not in sent


def test_context_montre_le_prompt_exact_sans_appeler_le_modele(env):
    """ADR-0058 : `/context` dans le chat web, sans tour de modèle ni enregistrement."""
    session_id = env.session()
    events = env.stream(session_id, "/context")
    assert types(events) == ["token", "done"] and events[1]["reason"] == "command"
    assert "--- [1] system" in events[0]["text"] and "num_ctx=" in events[0]["text"]
    assert env.script.calls == []
    assert env.get(f"/api/sessions/{session_id}").json()["messages"] == []
