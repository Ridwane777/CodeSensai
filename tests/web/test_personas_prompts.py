"""
[Lot A — Fresnel] Personas (A5) et versions de prompts (A4) dans le web :
ADR-0054 et ADR-0055.

- La persona est choisie par conversation, en mémoire du serveur (comme le CLI) :
  prompt système, outils désactivés (sous-agent compris) et cache contourné.
- Le registre des prompts est lu, jamais écrit : un essai de version ne vaut que
  pour une conversation.
"""
import threading
import time

import pytest

from sensai.core.events import Done, Token
from sensai.knowledge.persona import PersonaStore
from sensai.knowledge.prompt_versions import PromptStore
from tests.web.conftest import types

PERSONAS = {
    "default": "assistant",
    "profiles": [
        {"id": "assistant", "name": "Sensai", "role": "assistant de développement",
         "tone": "neutre", "scope": "le projet"},
        {"id": "relecteur", "name": "Relecteur", "role": "relecteur de code",
         "tone": "direct", "scope": "la relecture", "tools": {"disabled": ["write_file"]}},
    ],
}


@pytest.fixture
def penv(make_env):
    return make_env(personas=PersonaStore.from_config(PERSONAS))


def prompt_store(root):
    store = PromptStore(root / "prompts")
    store.save("system", "Prompt système v1.", "première", "Fresnel", date="2026-10-01")
    store.save("system", "Prompt système v2.", "deuxième", "Fresnel", date="2026-10-10")
    store.save("memory", "Reprise.", "mémoire", "Fresnel", date="2026-10-01")
    return store


@pytest.fixture
def prenv(make_env, tmp_path):
    store = prompt_store(tmp_path)
    store.use("system", "v1")
    return make_env(prompt_store=store)


# --- Personas (A5) ---------------------------------------------------------------------


def test_liste_des_personas(penv):
    personas = penv.get("/api/personas").json()
    assert [p["id"] for p in personas] == ["assistant", "relecteur"]
    assert personas[0]["default"] is True and personas[1]["default"] is False
    assert personas[1]["tools_disabled"] == ["write_file"]
    assert personas[1]["role"] == "relecteur de code"


def test_par_defaut_la_persona_de_la_config(penv):
    session_id = penv.session()
    assert penv.get(f"/api/sessions/{session_id}/persona").json()["id"] == "assistant"


def test_changer_de_persona_change_le_prompt_du_tour(penv):
    session_id = penv.session()
    response = penv.post(f"/api/sessions/{session_id}/persona", {"persona": "relecteur"})
    assert response.status_code == 200 and response.json()["id"] == "relecteur"
    assert penv.get(f"/api/sessions/{session_id}/persona").json()["id"] == "relecteur"
    penv.stream(session_id, "Bonjour")
    system = penv.script.calls[-1][0]["content"]
    assert penv.runtime.personas.get("relecteur").as_prompt() in system
    # Une autre conversation garde la persona par défaut.
    other = penv.session()
    penv.stream(other, "Bonjour")
    assert "tu es Sensai" in penv.script.calls[-1][0]["content"]


def test_persona_inconnue(penv):
    session_id = penv.session()
    response = penv.post(f"/api/sessions/{session_id}/persona", {"persona": "pirate"})
    assert response.status_code == 404 and response.json()["code"] == "PERSONA_NOT_FOUND"
    assert penv.post("/api/sessions/inconnue/persona",
                     {"persona": "relecteur"}).status_code == 404


def _during_turn(env, session_id, action):
    """Lance un tour lent et appelle `action` pendant qu'il tourne."""
    env.script.pause = 0.3
    env.script.steps = [Token("a"), Token("b"), Done("final_answer")]
    thread = threading.Thread(target=env.stream, args=(session_id, "Long"))
    thread.start()
    time.sleep(0.15)
    try:
        return action()
    finally:
        thread.join(timeout=10)


def test_pas_de_changement_de_persona_pendant_un_tour(penv):
    session_id = penv.session()
    response = _during_turn(penv, session_id, lambda: penv.post(
        f"/api/sessions/{session_id}/persona", {"persona": "relecteur"}))
    assert response.status_code == 409
    assert penv.get(f"/api/sessions/{session_id}/persona").json()["id"] == "assistant"


def test_la_persona_retire_write_file_a_l_agent_principal(penv):
    session_id = penv.session()
    penv.post(f"/api/sessions/{session_id}/persona", {"persona": "relecteur"})
    gateway = penv.runtime.make_gateway(lambda r: False,
                                        persona=penv.runtime.persona_of(session_id))
    assert "write_file" not in {t["name"] for t in gateway.describe_all()}
    penv.script.steps = [("call", "write_file", {"path": "x.txt", "content": "x"}),
                         Done("final_answer")]
    events = penv.stream(session_id, "Écris x.txt")
    returned = [e for e in events if e["type"] == "tool_return"]
    assert returned and returned[0]["ok"] is False
    assert "confirm_request" not in types(events)
    assert not (penv.project / "x.txt").exists()
    # La persona par défaut garde write_file.
    default = penv.runtime.make_gateway(lambda r: False)
    assert "write_file" in {t["name"] for t in default.describe_all()}


def test_la_persona_s_applique_au_sous_agent(penv, monkeypatch):
    seen = {}

    def faux_sous_agent(host, model, messages, tools, **kw):
        seen["system"] = messages[0]["content"]
        seen["offered"] = {t["name"] for t in tools.describe_all()}
        seen["result"] = tools.call("write_file", path="y.txt", content="y")
        yield Token("fait")
        yield Done("final_answer")

    monkeypatch.setattr("sensai.tools.delegate_tool._run_agent_turn", faux_sous_agent)
    session_id = penv.session()
    penv.post(f"/api/sessions/{session_id}/persona", {"persona": "relecteur"})
    penv.script.steps = [("call", "delegate_task", {"task": "écris y.txt"}),
                         Done("final_answer")]

    def approve(event):
        if event["type"] == "confirm_request":
            penv.post(f"/api/sessions/{session_id}/confirm",
                      {"confirm_id": event["confirm_id"], "approved": True})

    penv.stream(session_id, "Délègue", approve)
    assert "write_file" not in seen["offered"]
    assert seen["result"].ok is False
    assert penv.runtime.personas.get("relecteur").as_prompt() in seen["system"]
    assert not (penv.project / "y.txt").exists()


def test_une_persona_restrictive_ne_lit_ni_n_ecrit_le_cache(make_env):
    env = make_env(cache=True, personas=PersonaStore.from_config(PERSONAS))
    session_id = env.session()
    env.post(f"/api/sessions/{session_id}/persona", {"persona": "relecteur"})
    env.stream(session_id, "Comment lancer les tests ?")
    env.stream(session_id, "Comment lancer les tests ?")
    assert len(env.script.calls) == 2, "aucune réponse servie par le cache"
    other = env.session()
    events = env.stream(other, "Comment lancer les tests ?")
    assert "cache_hit" not in types(events), "rien n'a été rangé sous la persona restrictive"


def test_supprimer_la_conversation_oublie_sa_persona(penv):
    session_id = penv.session()
    penv.post(f"/api/sessions/{session_id}/persona", {"persona": "relecteur"})
    penv.post(f"/api/sessions/{session_id}/delete")
    assert penv.runtime.persona_of(session_id).id == "assistant"


# --- Versions de prompts (A4) ----------------------------------------------------------


def test_liste_du_registre(prenv):
    prompts = {p["name"]: p for p in prenv.get("/api/prompts").json()}
    assert set(prompts) == {"system", "memory"}
    system = prompts["system"]
    assert system["active"] == "v1"
    assert [v["id"] for v in system["versions"]] == ["v2", "v1"]
    assert system["versions"][1] == {"id": "v1", "date": "2026-10-01", "author": "Fresnel",
                                     "description": "première", "active": True}


def test_texte_et_diff_d_une_version(prenv):
    text = prenv.get("/api/prompts/system/v2").json()
    assert text == {"name": "system", "version": "v2", "text": "Prompt système v2."}
    diff = prenv.get("/api/prompts/system/diff", params={"a": "v1", "b": "v2"}).json()
    assert "-Prompt système v1." in diff["diff"] and "+Prompt système v2." in diff["diff"]
    assert prenv.get("/api/prompts/system/v9").status_code == 404
    assert prenv.get("/api/prompts/inconnu/v1").status_code == 404
    assert prenv.get("/api/prompts/system/diff", params={"a": "v1", "b": "v9"}).status_code == 404


def test_essai_d_une_version_dans_une_conversation(prenv):
    session_id = prenv.session()
    response = prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": "v2"})
    assert response.json() == {"prompt": "system", "active": "v1", "trial": "v2"}
    prenv.stream(session_id, "Bonjour")
    system = prenv.script.calls[-1][0]["content"]
    assert system.startswith("Prompt système v2.") and "Tu es CodeSensei." not in system
    # Une autre conversation garde le prompt chargé au démarrage.
    other = prenv.session()
    prenv.stream(other, "Bonjour")
    assert prenv.script.calls[-1][0]["content"].startswith("Tu es CodeSensei.")
    # Retour à la version active.
    back = prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": None}).json()
    assert back["trial"] is None
    prenv.stream(session_id, "Encore")
    assert prenv.script.calls[-1][0]["content"].startswith("Tu es CodeSensei.")


def test_essai_version_inconnue_ou_pendant_un_tour(prenv):
    session_id = prenv.session()
    response = prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": "v9"})
    assert response.status_code == 404 and response.json()["code"] == "PROMPT_VERSION_NOT_FOUND"
    busy = _during_turn(prenv, session_id, lambda: prenv.post(
        f"/api/sessions/{session_id}/prompt-trial", {"version": "v2"}))
    assert busy.status_code == 409
    assert prenv.get(f"/api/sessions/{session_id}/prompt-trial").json()["trial"] is None


def test_le_web_n_ecrit_jamais_le_registre(prenv):
    store = prenv.runtime.prompt_store
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    session_id = prenv.session()
    prenv.get("/api/prompts")
    prenv.get("/api/prompts/system/v2")
    prenv.get("/api/prompts/system/diff", params={"a": "v1", "b": "v2"})
    prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": "v2"})
    prenv.stream(session_id, "Bonjour")
    prenv.post(f"/api/sessions/{session_id}/prompt-trial", {"version": None})
    after = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert after == before


def test_un_essai_contourne_le_cache(make_env, tmp_path):
    env = make_env(cache=True, prompt_store=prompt_store(tmp_path))
    session_id = env.session()
    env.stream(session_id, "Comment lancer les tests ?")
    trial = env.session()
    env.post(f"/api/sessions/{trial}/prompt-trial", {"version": "v1"})
    events = env.stream(trial, "Comment lancer les tests ?")
    assert "cache_hit" not in types(events)
    assert len(env.script.calls) == 2
