"""
Teste A5 (persona) de bout en bout sur le vrai CLI, sans Ollama — ADR-0042
(le cœur : changer de persona en cours de session) et ADR-0043 (les
enrichissements : restriction d'outils par persona, routage automatique par
mots-clés, ajout d'une persona en session).

Même patron que `tests/test_cli_rag.py` : un faux agent reçoit la passerelle
et note ce qu'il observe (outils proposés, prompt système, messages envoyés).

Le test qui compte pour ADR-0042 est `test_persona_use_laisse_lhistorique_intact` :
c'est le critère principal de la story 2 (« changer de persona sans perdre le
contexte »).
"""
import builtins

import pytest

from sensai import cli
from sensai.core.events import Done, Token
from sensai.knowledge.memory import SESSIONS_FILE, SessionStore
from sensai.knowledge.persona import PersonaStore

DEUX_PERSONAS = {
    "default": "assistant",
    "profiles": [
        {"id": "assistant", "name": "Sensai", "role": "assistant", "tone": "neutre",
         "scope": "le projet"},
        {"id": "juridique", "name": "Maître Sensai", "role": "assistant juridique",
         "tone": "formel", "scope": "droit uniquement"},
    ],
}


@pytest.fixture
def lancer(tmp_path, monkeypatch):
    """Lance le CLI ; chaque tour observé note les outils proposés, le prompt
    système et une copie des messages reçus par le faux agent."""

    def _lancer(entrees, *, personas=None, **options):
        settings = {
            "model": "faux-modele",
            "host": "http://localhost:11434",
            "system_prompt": "Tu es CodeSensei.",
            "session": None,
            "new_session": False,
            "data_dir": str(tmp_path / "donnees"),
            "retention_days": 30,
            "rag": False,
            "rag_min_score": 0.0,
        }
        if personas is not None:
            settings["personas"] = personas
        settings.update(options)
        observe = []

        def faux_agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
            observe.append({
                "outils": [d["name"] for d in tools.describe_all()],
                "systeme": messages[0]["content"],
                "messages": [dict(m) for m in messages],
            })
            yield Token(text="D'accord.")
            yield Done()

        restantes = iter(entrees)

        def faux_input(_prompt=""):
            try:
                return next(restantes)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        monkeypatch.setattr(cli, "run_agent_turn", faux_agent)
        monkeypatch.setattr(builtins, "input", faux_input)
        cli.main()
        return observe

    return _lancer


def test_sans_section_personas_aucune_persona_juridique(lancer):
    observe = lancer(["Bonjour"])
    assert "assistant juridique" not in observe[0]["systeme"]


def test_persona_use_change_le_prompt_systeme_au_tour_suivant(lancer):
    observe = lancer(
        ["Bonjour", "/persona use juridique", "Et ensuite ?"],
        personas=PersonaStore.from_config(DEUX_PERSONAS),
    )
    assert len(observe) == 2  # la commande ne va pas au modèle
    assert "assistant juridique" not in observe[0]["systeme"]
    assert "assistant juridique" in observe[1]["systeme"]


def test_persona_use_laisse_lhistorique_intact(lancer, tmp_path):
    """Après le changement, le modèle voit toujours tout ce qui a été dit avant,
    et rien n'est écrit dans la session sauvegardée à propos de la persona."""
    observe = lancer(
        ["première question", "/persona use juridique", "seconde question"],
        personas=PersonaStore.from_config(DEUX_PERSONAS),
    )

    # Tour 2 : système (nouveau), puis les deux messages du tour 1, puis la
    # nouvelle question — l'historique n'a pas bougé.
    tour2 = observe[1]["messages"]
    assert [m["role"] for m in tour2] == ["system", "user", "assistant", "user"]
    assert tour2[1]["content"] == "première question"
    assert tour2[2]["content"] == "D'accord."
    assert tour2[3]["content"] == "seconde question"

    store = SessionStore(tmp_path / "donnees" / SESSIONS_FILE)
    sauvegardes = store.load(store.list()[0].id)
    assert [(t["role"], t["content"]) for t in sauvegardes] == [
        ("user", "première question"),
        ("assistant", "D'accord."),
        ("user", "seconde question"),
        ("assistant", "D'accord."),
    ]


def test_persona_inconnue_ne_change_rien_au_prompt(lancer):
    observe = lancer(
        ["/persona use inexistante", "Bonjour"],
        personas=PersonaStore.from_config(DEUX_PERSONAS),
    )
    assert "assistant juridique" not in observe[0]["systeme"]


def test_les_sous_agents_du_cli_recoivent_la_persona_active(lancer, monkeypatch):
    """`DelegateTool` reçoit le même `system_prompt()` que la boucle du CLI :
    un sous-agent lancé après `/persona use` hérite donc de la persona active."""
    instances = []

    class DelegateEspion(cli.DelegateTool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(cli, "DelegateTool", DelegateEspion)
    lancer(
        ["/persona use juridique", "Bonjour"],
        personas=PersonaStore.from_config(DEUX_PERSONAS),
    )
    assert "assistant juridique" in instances[0]._system(None, None)


def test_persona_sans_restriction_propose_tous_les_outils(lancer):
    observe = lancer(["Bonjour"])
    assert "search_codebase" not in observe[0]["outils"]  # rag=False : pas proposé de toute façon
    assert "run_code" in observe[0]["outils"]


def test_persona_avec_outils_restreints_les_retire(lancer):
    personas = PersonaStore.from_config({
        "default": "tuteur",
        "profiles": [
            {"id": "tuteur", "name": "Prof Sensai", "role": "tuteur de maths", "tone": "doux",
             "scope": "maths", "tools": {"disabled": ["run_code"]}},
        ],
    })
    observe = lancer(["Bonjour"], personas=personas)
    assert "run_code" not in observe[0]["outils"]


def test_persona_use_applique_la_restriction_au_tour_suivant(lancer):
    personas = PersonaStore.from_config({
        "default": "assistant",
        "profiles": [
            {"id": "assistant", "name": "Sensai", "role": "assistant", "tone": "neutre",
             "scope": "le projet"},
            {"id": "tuteur", "name": "Prof Sensai", "role": "tuteur de maths", "tone": "doux",
             "scope": "maths", "tools": {"disabled": ["run_code"]}},
        ],
    })
    observe = lancer(["/persona use tuteur", "Bonjour"], personas=personas)
    assert len(observe) == 1  # la commande ne va pas au modèle
    assert "run_code" not in observe[0]["outils"]


def test_persona_choisie_a_la_main_ne_revient_pas_seule(lancer):
    """Un /persona use explicite n'est jamais défait par l'absence de
    mot-clé au tour suivant (revue PR #95)."""
    personas = PersonaStore.from_config({
        "default": "assistant",
        "profiles": [
            {"id": "assistant", "name": "Sensai", "role": "assistant", "tone": "neutre",
             "scope": "le projet"},
            {"id": "juridique", "name": "Maître Sensai", "role": "assistant juridique",
             "tone": "formel", "scope": "droit uniquement"},
        ],
    })
    observe = lancer(
        ["/persona use juridique", "Et sinon, comment ça va ?"], personas=personas
    )
    assert "assistant juridique" in observe[0]["systeme"]


TUTEUR_SANS_CODE = {
    "default": "tuteur",
    "profiles": [
        {"id": "tuteur", "name": "Prof Sensai", "role": "tuteur de maths", "tone": "doux",
         "scope": "maths", "tools": {"disabled": ["run_code"]}},
    ],
}


@pytest.fixture
def espions(monkeypatch):
    """Capture le `DelegateTool` et le `TeamTool` créés par le CLI pour que
    le test puisse ensuite les faire travailler avec un faux sous-agent."""
    delegates, teams = [], []

    class DelegateEspion(cli.DelegateTool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            delegates.append(self)

    class TeamEspion(cli.TeamTool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            teams.append(self)

    monkeypatch.setattr(cli, "DelegateTool", DelegateEspion)
    monkeypatch.setattr(cli, "TeamTool", TeamEspion)
    return delegates, teams


def test_delegate_task_refuse_un_outil_desactive_par_la_persona(lancer, espions):
    """Revue PR #95 : la restriction vaut aussi pour les sous-agents, qui
    partagent la passerelle du CLI — rien ne le garantissait par un test."""
    delegates, _ = espions
    lancer(["Bonjour"], personas=PersonaStore.from_config(TUTEUR_SANS_CODE))
    refus = []

    def sous_agent(host, model, messages, tools):
        refus.append(tools.call("run_code", code="print(1)").data.get("error"))
        yield Token(text="fini")
        yield Done()

    delegates[0].run_turn = sous_agent
    delegates[0].run(task="exécute du code")

    assert refus == ["disabled"]


def test_team_task_refuse_un_outil_desactive_par_la_persona(lancer, espions):
    """Dans l'équipe, seul le développeur a `run_code` dans son rôle : c'est lui
    qui rencontre le refus de la passerelle (« disabled »). Les autres rôles
    sont déjà refusés par leur propre filtre, jamais exécutés."""
    delegates, teams = espions
    lancer(["Bonjour"], personas=PersonaStore.from_config(TUTEUR_SANS_CODE))
    resultats = []

    def sous_agent(host, model, messages, tools):
        resultats.append(tools.call("run_code", code="print(1)"))
        yield Token(text="VALIDÉ, rien à redire")
        yield Done()

    delegates[0].run_turn = sous_agent
    teams[0].run(task="écris un script")

    assert resultats, "au moins un sous-agent de l'équipe a tenté l'outil"
    assert not any(r.ok for r in resultats), "aucun sous-agent n'a pu exécuter run_code"
    assert "disabled" in [r.data.get("error") for r in resultats]
