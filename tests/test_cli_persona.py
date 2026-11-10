"""
Tests A5 (persona) end to end on the real CLI, without Ollama — ADR-0042
(the core: switching persona mid-session) and ADR-0043 (the extras:
per-persona tool restriction, automatic keyword routing, adding a persona
during a session).

Same pattern as `tests/test_cli_rag.py`: a fake agent receives the gateway
and records what it sees (offered tools, system prompt, sent messages).

The test that matters for ADR-0042 is `test_persona_use_keeps_history_intact`:
it is the main criterion of story 2 ("switch persona without losing the
context").
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
        {"id": "assistant", "name": "CodeSensai", "role": "assistant", "tone": "neutral",
         "scope": "the project"},
        {"id": "juridique", "name": "Counsel CodeSensai", "role": "legal assistant",
         "tone": "formal", "scope": "law only"},
    ],
}


@pytest.fixture
def lancer(tmp_path, monkeypatch):
    """Run the CLI; each observed turn records the offered tools, the system
    prompt and a copy of the messages received by the fake agent."""

    def _lancer(entrees, *, personas=None, **options):
        settings = {
            "model": "fake-model",
            "host": "http://localhost:11434",
            "system_prompt": "You are CodeSensai.",
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
            yield Token(text="Got it.")
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


def test_without_personas_section_no_legal_persona(lancer):
    observe = lancer(["Hello"])
    assert "legal assistant" not in observe[0]["systeme"]


def test_persona_use_changes_system_prompt_next_turn(lancer):
    observe = lancer(
        ["Hello", "/persona use juridique", "And then?"],
        personas=PersonaStore.from_config(DEUX_PERSONAS),
    )
    assert len(observe) == 2  # the command does not go to the model
    assert "legal assistant" not in observe[0]["systeme"]
    assert "legal assistant" in observe[1]["systeme"]


def test_persona_use_keeps_history_intact(lancer, tmp_path):
    """After the switch, the model still sees everything said before, and
    nothing about the persona is written to the saved session."""
    observe = lancer(
        ["first question", "/persona use juridique", "second question"],
        personas=PersonaStore.from_config(DEUX_PERSONAS),
    )

    # Turn 2: system (new), then the two messages of turn 1, then the new
    # question — the history has not changed.
    tour2 = observe[1]["messages"]
    assert [m["role"] for m in tour2] == ["system", "user", "assistant", "user"]
    assert tour2[1]["content"] == "first question"
    assert tour2[2]["content"] == "Got it."
    assert tour2[3]["content"] == "second question"

    store = SessionStore(tmp_path / "donnees" / SESSIONS_FILE)
    sauvegardes = store.load(store.list()[0].id)
    assert [(t["role"], t["content"]) for t in sauvegardes] == [
        ("user", "first question"),
        ("assistant", "Got it."),
        ("user", "second question"),
        ("assistant", "Got it."),
    ]


def test_unknown_persona_leaves_prompt_unchanged(lancer):
    observe = lancer(
        ["/persona use nonexistent", "Hello"],
        personas=PersonaStore.from_config(DEUX_PERSONAS),
    )
    assert "legal assistant" not in observe[0]["systeme"]


def test_cli_subagents_get_the_active_persona(lancer, monkeypatch):
    """`DelegateTool` gets the same `system_prompt()` as the CLI loop, so a
    subagent started after `/persona use` inherits the active persona."""
    instances = []

    class DelegateEspion(cli.DelegateTool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(cli, "DelegateTool", DelegateEspion)
    lancer(
        ["/persona use juridique", "Hello"],
        personas=PersonaStore.from_config(DEUX_PERSONAS),
    )
    assert "legal assistant" in instances[0]._system(None, None)


def test_persona_without_restriction_offers_all_tools(lancer):
    observe = lancer(["Hello"])
    assert "search_codebase" not in observe[0]["outils"]  # rag=False: not offered anyway
    assert "run_code" in observe[0]["outils"]


def test_persona_with_restricted_tools_removes_them(lancer):
    personas = PersonaStore.from_config({
        "default": "tuteur",
        "profiles": [
            {"id": "tuteur", "name": "Prof CodeSensai", "role": "math tutor", "tone": "gentle",
             "scope": "maths", "tools": {"disabled": ["run_code"]}},
        ],
    })
    observe = lancer(["Hello"], personas=personas)
    assert "run_code" not in observe[0]["outils"]


def test_persona_use_applies_restriction_next_turn(lancer):
    personas = PersonaStore.from_config({
        "default": "assistant",
        "profiles": [
            {"id": "assistant", "name": "CodeSensai", "role": "assistant", "tone": "neutral",
             "scope": "the project"},
            {"id": "tuteur", "name": "Prof CodeSensai", "role": "math tutor", "tone": "gentle",
             "scope": "maths", "tools": {"disabled": ["run_code"]}},
        ],
    })
    observe = lancer(["/persona use tuteur", "Hello"], personas=personas)
    assert len(observe) == 1  # the command does not go to the model
    assert "run_code" not in observe[0]["outils"]


def test_manually_chosen_persona_does_not_revert(lancer):
    """An explicit /persona use is never undone by a missing keyword on the
    next turn (PR #95 review)."""
    personas = PersonaStore.from_config({
        "default": "assistant",
        "profiles": [
            {"id": "assistant", "name": "CodeSensai", "role": "assistant", "tone": "neutral",
             "scope": "the project"},
            {"id": "juridique", "name": "Counsel CodeSensai", "role": "legal assistant",
             "tone": "formal", "scope": "law only"},
        ],
    })
    observe = lancer(
        ["/persona use juridique", "By the way, how are you?"], personas=personas
    )
    assert "legal assistant" in observe[0]["systeme"]


TUTEUR_SANS_CODE = {
    "default": "tuteur",
    "profiles": [
        {"id": "tuteur", "name": "Prof CodeSensai", "role": "math tutor", "tone": "gentle",
         "scope": "maths", "tools": {"disabled": ["run_code"]}},
    ],
}


@pytest.fixture
def espions(monkeypatch):
    """Capture the `DelegateTool` and `TeamTool` created by the CLI so the
    test can then run them with a fake subagent."""
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


def test_delegate_task_refuses_a_tool_disabled_by_persona(lancer, espions):
    """PR #95 review: the restriction also applies to subagents, which share
    the CLI gateway — no test guaranteed it."""
    delegates, _ = espions
    lancer(["Hello"], personas=PersonaStore.from_config(TUTEUR_SANS_CODE))
    refus = []

    def sous_agent(host, model, messages, tools):
        refus.append(tools.call("run_code", code="print(1)").data.get("error"))
        yield Token(text="done")
        yield Done()

    delegates[0].run_turn = sous_agent
    delegates[0].run(task="run some code")

    assert refus == ["disabled"]


def test_team_task_refuses_a_tool_disabled_by_persona(lancer, espions):
    """In the team, only the developer has `run_code` in its role: it is the one
    that hits the gateway refusal ("disabled"). The other roles are already
    refused by their own filter, never executed."""
    delegates, teams = espions
    lancer(["Hello"], personas=PersonaStore.from_config(TUTEUR_SANS_CODE))
    resultats = []

    def sous_agent(host, model, messages, tools):
        resultats.append(tools.call("run_code", code="print(1)"))
        # "VALIDÉ" is the verdict keyword parsed by team_tool.verdict (still French).
        yield Token(text="VALIDÉ, nothing to add")
        yield Done()

    delegates[0].run_turn = sous_agent
    teams[0].run(task="write a script")

    assert resultats, "at least one team subagent tried the tool"
    assert not any(r.ok for r in resultats), "no subagent could run run_code"
    assert "disabled" in [r.data.get("error") for r in resultats]
