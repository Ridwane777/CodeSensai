"""
Tests R1 end to end on the real CLI, without Ollama: chat is replaced by a
fake model that records what it receives, embeddings by the bag of words
from tests/knowledge/test_rag.py.

What matters is what the model *sees*. R1's DoD ("the answer cites the right
passage") assumes the passage and its source reach the message sent to the
model — that is what `test_premiere_question_indexe_et_cite` checks.

`test_le_contexte_n_est_pas_sauvegarde_dans_la_session` protects M1: injected
passages must not pile up in the saved history.
"""
import builtins

import pytest

from sensai import cli
from sensai.core.events import Done, Token
from sensai.execution.sandbox.document_sandbox import ConversionResult
from sensai.knowledge.memory import SESSIONS_FILE, SessionStore
from sensai.knowledge.rag import EmbeddingError
from tests.knowledge.test_rag import FauxEmbedder


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = tmp_path / "projet"
    (racine / "src").mkdir(parents=True)
    (racine / "src" / "auth.py").write_text(
        "import hmac\n"
        "\n"
        "\n"
        "def verifier_token(token, secret):\n"
        '    """Checks the login token sent by the client."""\n'
        "    return hmac.compare_digest(token, secret)\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(racine)
    return racine


@pytest.fixture
def lancer(tmp_path, monkeypatch, projet):
    """Runs the CLI with keyboard inputs; returns (messages sent, embedder)."""

    def _lancer(entrees, *, embedder=None, **options):
        settings = {
            "model": "fake-model",
            "host": "http://localhost:11434",
            "system_prompt": "You are CodeSensai.",
            "session": None,
            "new_session": False,
            "data_dir": str(tmp_path / "donnees"),
            "retention_days": 30,
            "rag": True,
            "rag_model": "bge-m3",
            "rag_min_score": 0.0,
            "rag_top_k": 3,
        }
        settings.update(options)
        embedder = embedder or FauxEmbedder()
        envoyes = []

        def faux_stream_chat(host, model, messages):
            envoyes.append([dict(m) for m in messages])
            yield "Got it."

        restantes = iter(entrees)

        def faux_input(_prompt=""):
            try:
                return next(restantes)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        monkeypatch.setattr(cli, "stream_chat", faux_stream_chat)
        monkeypatch.setattr(cli, "OllamaEmbedder", lambda host, model: embedder)
        # Never the real Docker in tests: conversion "fails" as it would
        # without the sensai-docs image (ADR-0034).
        monkeypatch.setattr(cli, "DocumentSandbox", lambda: lambda path, ext=None:
                            ConversionResult(False, error="image_missing"))
        monkeypatch.setattr(builtins, "input", faux_input)
        cli.main()
        return envoyes, embedder

    return _lancer


def test_premiere_question_indexe_et_cite(lancer, capsys):
    envoyes, _ = lancer(["Where is the login token checked?"])

    question = envoyes[0][-1]
    assert question["role"] == "user"
    assert "src/auth.py:4-6" in question["content"]
    assert "Where is the login token checked?" in question["content"]
    assert "index" in capsys.readouterr().out.lower(), "indexing must be announced"


def test_l_indexation_n_a_lieu_qu_une_fois_par_session(lancer):
    _, embedder = lancer(["First question about the token", "Second question about the token"])

    # 1 indexed passage + 2 questions: nothing is reindexed on the second turn.
    assert embedder.texts_received == 3


def test_le_contexte_n_est_pas_sauvegarde_dans_la_session(lancer, tmp_path):
    lancer(["Where is the login token checked?"])

    store = SessionStore(tmp_path / "donnees" / SESSIONS_FILE)
    turns = store.load(store.list()[0].id)
    assert turns[0] == {"role": "user", "content": "Where is the login token checked?"}


def test_une_commande_ne_declenche_pas_l_indexation(lancer):
    _, embedder = lancer(["/profile"])

    assert embedder.texts_received == 0


def test_rag_desactivable(lancer):
    envoyes, embedder = lancer(["Where is the token checked?"], rag=False)

    assert embedder.texts_received == 0
    assert envoyes[0][-1]["content"] == "Where is the token checked?"


class EmbedderEnPanne:
    texts_received = 0

    def __call__(self, textes):
        raise EmbeddingError("model bge-m3 not found: ollama pull bge-m3")


def test_ollama_indisponible_la_conversation_continue(lancer, capsys):
    envoyes, _ = lancer(["First question", "Second question"], embedder=EmbedderEnPanne())

    assert len(envoyes) == 2, "both questions must have been answered"
    assert envoyes[1][-1]["content"] == "Second question"
    assert "ollama pull bge-m3" in capsys.readouterr().out


def test_format_non_pris_en_charge_signale(lancer, projet, capsys):
    (projet / "requirements.pdf").write_bytes(b"%PDF-1.7\n\x00binary")

    lancer(["A question"])

    assert "requirements.pdf" in capsys.readouterr().out


# --- The search_codebase tool for the ReAct loop (ADR-0013) ----------------


@pytest.fixture
def lancer_agent(tmp_path, monkeypatch, projet):
    """Runs the CLI on the real agent path: `run_agent_turn` is replaced by a
    fake agent that calls `search_codebase` through the gateway it receives,
    as the model would. Returns what it observed."""

    def _lancer(entrees, *, embedder=None, appels=(), confirmer=None, **options):
        settings = {
            "model": "fake-model",
            "host": "http://localhost:11434",
            "system_prompt": "You are CodeSensai.",
            "session": None,
            "new_session": False,
            "data_dir": str(tmp_path / "donnees"),
            "retention_days": 30,
            "rag": True,
            "rag_model": "bge-m3",
            "rag_min_score": 0.0,
            "rag_top_k": 3,
        }
        settings.update(options)
        observe = []

        def faux_agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
            noms = [d["name"] for d in tools.describe_all()]
            appel = None
            if "search_codebase" in noms:
                appel = tools.call("search_codebase", query="token")
            resultats = [tools.call(nom, **args) for nom, args in appels]
            observe.append({
                "outils": noms, "appel": appel, "resultats": resultats,
                "systeme": messages[0]["content"],
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
        if confirmer is not None:
            monkeypatch.setattr(cli, "confirm_in_terminal", confirmer)
        monkeypatch.setattr(cli, "OllamaEmbedder", lambda host, model: embedder or FauxEmbedder())
        monkeypatch.setattr(builtins, "input", faux_input)
        cli.main()
        return observe

    return _lancer


def test_l_agent_cherche_lui_meme_dans_le_projet(lancer_agent):
    """The tool receives the index opened on the first question, before the agent."""
    observe = lancer_agent(["Where is the login token checked?"])

    assert "search_codebase" in observe[0]["outils"]
    appel = observe[0]["appel"]
    assert appel.ok, appel.content
    assert "src/auth.py:4-6" in appel.content


def test_sans_rag_l_outil_n_est_pas_propose(lancer_agent):
    observe = lancer_agent(["Where is the token checked?"], rag=False)

    assert "search_codebase" not in observe[0]["outils"]


def test_index_indisponible_l_outil_repond_proprement(lancer_agent):
    """Indexing failed: search is turned off, the tool answers without crashing."""
    observe = lancer_agent(["A question"], embedder=EmbedderEnPanne())

    appel = observe[0]["appel"]
    assert appel is not None and not appel.ok
    assert "unavailable" in appel.content.lower()


def test_l_outil_suit_les_reglages_du_rag(lancer_agent):
    """--rag-min-score also applies to the agent's searches."""
    observe = lancer_agent(["Where is the token checked?"], rag_min_score=0.99)

    appel = observe[0]["appel"]
    assert "src/auth.py" not in appel.content


def test_l_outil_ignore_la_limite_des_passages_automatiques(lancer_agent, projet):
    """--rag-top-k limits what is added to each question, not the searches
    requested by the model (real trial run of 2026-10-14)."""
    (projet / "src" / "session.py").write_text(
        "def ouvrir_session(token):\n"
        '    """Opens a session from the token."""\n'
        "    return {'token': token}\n",
        encoding="utf-8",
    )
    observe = lancer_agent(["Where is the token used?"], rag_top_k=1)

    appel = observe[0]["appel"]
    assert "src/auth.py" in appel.content
    assert "src/session.py" in appel.content


def test_les_garde_fous_masquent_les_secrets_trouves_par_l_outil(lancer_agent, projet):
    """OUT-15 (EV4): a project passage containing an API key must not reach
    the model in clear text. Fake key, in the format of a real one."""
    (projet / "src" / "reglages.py").write_text(
        "# login token for the service\n"
        'API_KEY = "sk-abcdef1234567890abcdef"\n',
        encoding="utf-8",
    )
    observe = lancer_agent(["Where is the token?"])

    appel = observe[0]["appel"]
    assert "src/reglages.py" in appel.content
    assert "sk-abcdef1234567890abcdef" not in appel.content


def test_un_outil_desactive_dans_la_config_n_est_pas_propose(lancer_agent):
    from sensai.execution.tool_policy import ToolPreferences

    observe = lancer_agent(
        ["A question"], tool_preferences=ToolPreferences(disabled=frozenset({"web_search"}))
    )

    assert "web_search" not in observe[0]["outils"]
    assert "read_file" in observe[0]["outils"]


def test_les_dossiers_autorises_de_la_config_s_appliquent(lancer_agent, projet):
    """`files.read` restricts read_file to the chosen folder (ADR-0011)."""
    from sensai.execution.file_permissions import FilePermissions

    (projet / "docs").mkdir()
    (projet / "docs" / "notes.md").write_text("notes", encoding="utf-8")
    observe = lancer_agent(
        ["A question"],
        file_permissions=FilePermissions.from_dict({"root": str(projet), "read": ["docs"]}),
        appels=[("read_file", {"path": "docs/notes.md"}), ("read_file", {"path": "src/auth.py"})],
    )

    docs, src = observe[0]["resultats"]
    assert docs.ok
    assert not src.ok


# --- Project state document (M4, ADR-0029) ------------------------------------


def test_l_agent_peut_mettre_a_jour_le_document_d_etat(lancer_agent):
    observe = lancer_agent(["A question"])

    assert "update_state" in observe[0]["outils"]


def test_le_document_d_etat_est_dans_le_prompt_systeme(lancer_agent, projet):
    """US-M4-1: the agent knows it from the first message, without rereading it."""
    (projet / "SENSAI.md").write_text("## In progress\n\n- R2: reranking\n", encoding="utf-8")

    observe = lancer_agent(["Where do we stand?"])

    assert "- R2: reranking" in observe[0]["systeme"]


def test_le_prompt_suit_la_mise_a_jour_du_document(lancer_agent, projet, monkeypatch):
    """After an accepted update, the next turn sees the new version."""
    reponses = iter([True])
    observe = lancer_agent(
        ["First", "Second"],
        appels=[("update_state", {"section": "In progress", "action": "replace", "content": "- M4"})],
        confirmer=lambda request: next(reponses, False),
    )

    assert "- M4" not in observe[0]["systeme"]
    assert "- M4" in observe[1]["systeme"]


def test_commande_state_affiche_le_document(lancer_agent, projet, capsys):
    (projet / "SENSAI.md").write_text("## Fait\n\n- M1\n", encoding="utf-8")

    lancer_agent(["/state"])

    assert "- M1" in capsys.readouterr().out


# --- Structured memory (M3, ADR-0030) -----------------------------------------


def test_l_agent_peut_retenir_et_retrouver_des_faits(lancer_agent):
    observe = lancer_agent(["A question"])

    assert {"save_fact", "recall_facts"} <= set(observe[0]["outils"])


def test_un_fait_retenu_est_connu_dans_une_nouvelle_session(lancer_agent):
    """US-M3-1 and 2: the fact survives closing the CLI, and the entity is
    announced in the system prompt of the next session."""
    lancer_agent(
        ["First"],
        appels=[("save_fact", {"entity": "auth", "attribute": "version_redis", "value": "7"})],
        confirmer=lambda request: True,
    )

    observe = lancer_agent(
        ["Which Redis version?"], new_session=True,
        appels=[("recall_facts", {"entity": "auth"})],
    )

    assert "auth" in observe[0]["systeme"]
    assert "7" in observe[0]["resultats"][0].content


def test_commande_facts(lancer_agent, capsys):
    lancer_agent(
        ["First"],
        appels=[("save_fact", {"entity": "auth", "attribute": "version_redis", "value": "7"})],
        confirmer=lambda request: True,
    )
    capsys.readouterr()

    lancer_agent(["/facts auth", "/facts forget auth version_redis", "/facts auth"],
                 new_session=True)

    sortie = capsys.readouterr().out
    assert "version_redis" in sortie and "7" in sortie
    assert "No facts" in sortie


def test_les_passages_ajoutes_a_la_question_sont_filtres(lancer, projet):
    """EV2: the passages that search adds on its own to each question go
    through the same filter as tool outputs. Real trial run of 2026-10-24:
    the key in reglages.py reached the model in clear text, and the model
    displayed it without calling read_file. Fake key, in the format of a real one."""
    (projet / "src" / "reglages.py").write_text(
        "# login token for the service\n"
        'API_KEY = "sk-abcdef1234567890abcdef"\n',
        encoding="utf-8",
    )
    envoyes, _ = lancer(["Where is the login token?"])

    question = envoyes[0][-1]["content"]
    assert "src/reglages.py" in question, "the passage is still sent to the model"
    assert "sk-abcdef1234567890abcdef" not in question


def test_structured_s_appuie_sur_ce_que_l_agent_a_trouve(lancer, projet, monkeypatch):
    """T5 (ADR-0039): /structured first lets the agent search (here the fake
    model answers "Got it."), then formats from its answer."""
    import json

    from sensai.core import structured

    (projet / "schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    vus = []

    def fausse_mise_en_forme(host, model, prompt, schema):
        vus.append(prompt)
        return {"ok": True}

    original = structured.handle_structured_command
    monkeypatch.setattr(cli, "handle_structured_command",
                        lambda line, **kw: original(line, query=fausse_mise_en_forme, **kw))

    envoyes, _ = lancer(["/structured schema.json list the functions in src/auth.py"])

    assert envoyes, "the agent was called to search"
    assert "list the functions in src/auth.py" in envoyes[0][-1]["content"]
    assert vus and "Got it." in vus[0] and "list the functions" in vus[0]


def test_structured_en_premiere_commande_a_une_recherche_qui_marche(lancer_agent, projet,
                                                                     monkeypatch):
    """Trial run of 2026-11-06 (T5): typed before any question, /structured left
    `search_codebase` without an index ("project not indexed") and the agent
    guessed file names. The index must be open before its search phase."""
    import json

    from sensai.core import structured

    (projet / "schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    original = structured.handle_structured_command
    monkeypatch.setattr(cli, "handle_structured_command", lambda line, **kw: original(
        line, query=lambda host, model, prompt, schema: {"ok": True}, **kw))

    observe = lancer_agent(["/structured schema.json Where is the token checked?"])

    appel = observe[0]["appel"]
    assert appel is not None and appel.ok, appel.content if appel else "tool missing"
    assert "src/auth.py" in appel.content


def test_les_outils_mcp_de_la_config_sont_proposes(lancer_agent, capsys):
    """T1 (ADR-0041): the tools of an MCP server declared in config.json are
    offered to the agent; a server that cannot be found does not block startup."""
    import sys
    from pathlib import Path

    serveur = str(Path(__file__).parent / "tools" / "fake_mcp_server.py")
    observe = lancer_agent(["Add 2 and 3."], mcp_servers={
        "fake": {"command": sys.executable, "args": [serveur], "env": {}, "cwd": None,
                 "risk": "execute", "timeout_s": 10.0},
        "absent": {"command": "command-that-does-not-exist-xyz", "args": [], "env": {},
                   "cwd": None, "risk": "execute", "timeout_s": 10.0},
    })

    assert "mcp_fake_add" in observe[0]["outils"]
    assert "absent" in capsys.readouterr().out, "the failure is reported"
