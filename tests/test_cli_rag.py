"""
Teste R1 de bout en bout sur le vrai CLI, sans Ollama : le chat est remplacé
par un faux modèle qui note ce qu'il reçoit, les embeddings par le sac de mots
de tests/knowledge/test_rag.py.

Ce qui compte : ce que le modèle *voit*. La DoD de R1 (« la réponse cite le
bon passage ») suppose que le passage et sa source arrivent dans le message
envoyé au modèle — c'est ce que vérifie `test_premiere_question_indexe_et_cite`.

`test_le_contexte_n_est_pas_sauvegarde_dans_la_session` protège M1 : les
passages injectés ne doivent pas s'accumuler dans l'historique enregistré.
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
        '    """Vérifie le token de connexion envoyé par le client."""\n'
        "    return hmac.compare_digest(token, secret)\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(racine)
    return racine


@pytest.fixture
def lancer(tmp_path, monkeypatch, projet):
    """Lance le CLI avec des entrées clavier ; renvoie (messages envoyés, embedder)."""

    def _lancer(entrees, *, embedder=None, **options):
        settings = {
            "model": "faux-modele",
            "host": "http://localhost:11434",
            "system_prompt": "Tu es CodeSensei.",
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
            yield "D'accord."

        restantes = iter(entrees)

        def faux_input(_prompt=""):
            try:
                return next(restantes)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        monkeypatch.setattr(cli, "stream_chat", faux_stream_chat)
        monkeypatch.setattr(cli, "OllamaEmbedder", lambda host, model: embedder)
        # Jamais le vrai Docker dans les tests : la conversion « échoue » comme
        # sans l'image sensai-docs (ADR-0034).
        monkeypatch.setattr(cli, "DocumentSandbox", lambda: lambda path, ext=None:
                            ConversionResult(False, error="image_missing"))
        monkeypatch.setattr(builtins, "input", faux_input)
        cli.main()
        return envoyes, embedder

    return _lancer


def test_premiere_question_indexe_et_cite(lancer, capsys):
    envoyes, _ = lancer(["Où vérifie-t-on le token de connexion ?"])

    question = envoyes[0][-1]
    assert question["role"] == "user"
    assert "src/auth.py:4-6" in question["content"]
    assert "Où vérifie-t-on le token de connexion ?" in question["content"]
    assert "index" in capsys.readouterr().out.lower(), "l'indexation doit être annoncée"


def test_l_indexation_n_a_lieu_qu_une_fois_par_session(lancer):
    _, embedder = lancer(["Première question sur le token", "Seconde question sur le token"])

    # 1 passage indexé + 2 questions : rien n'est réindexé au second tour.
    assert embedder.textes_recus == 3


def test_le_contexte_n_est_pas_sauvegarde_dans_la_session(lancer, tmp_path):
    lancer(["Où vérifie-t-on le token de connexion ?"])

    store = SessionStore(tmp_path / "donnees" / SESSIONS_FILE)
    turns = store.load(store.list()[0].id)
    assert turns[0] == {"role": "user", "content": "Où vérifie-t-on le token de connexion ?"}


def test_une_commande_ne_declenche_pas_l_indexation(lancer):
    _, embedder = lancer(["/profile"])

    assert embedder.textes_recus == 0


def test_rag_desactivable(lancer):
    envoyes, embedder = lancer(["Où vérifie-t-on le token ?"], rag=False)

    assert embedder.textes_recus == 0
    assert envoyes[0][-1]["content"] == "Où vérifie-t-on le token ?"


class EmbedderEnPanne:
    textes_recus = 0

    def __call__(self, textes):
        raise EmbeddingError("modèle bge-m3 introuvable : ollama pull bge-m3")


def test_ollama_indisponible_la_conversation_continue(lancer, capsys):
    envoyes, _ = lancer(["Première question", "Seconde question"], embedder=EmbedderEnPanne())

    assert len(envoyes) == 2, "les deux questions doivent avoir reçu une réponse"
    assert envoyes[1][-1]["content"] == "Seconde question"
    assert "ollama pull bge-m3" in capsys.readouterr().out


def test_format_non_pris_en_charge_signale(lancer, projet, capsys):
    (projet / "sujet.pdf").write_bytes(b"%PDF-1.7\n\x00binaire")

    lancer(["Une question"])

    assert "sujet.pdf" in capsys.readouterr().out


# --- L'outil search_codebase pour la boucle ReAct (ADR-0013) ----------------


@pytest.fixture
def lancer_agent(tmp_path, monkeypatch, projet):
    """Lance le CLI sur le vrai chemin de l'agent : `run_agent_turn` est
    remplacé par un faux agent qui appelle `search_codebase` à travers la
    passerelle reçue, comme le ferait le modèle. Renvoie ce qu'il a observé."""

    def _lancer(entrees, *, embedder=None, appels=(), confirmer=None, **options):
        settings = {
            "model": "faux-modele",
            "host": "http://localhost:11434",
            "system_prompt": "Tu es CodeSensei.",
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
        if confirmer is not None:
            monkeypatch.setattr(cli, "confirm_in_terminal", confirmer)
        monkeypatch.setattr(cli, "OllamaEmbedder", lambda host, model: embedder or FauxEmbedder())
        monkeypatch.setattr(builtins, "input", faux_input)
        cli.main()
        return observe

    return _lancer


def test_l_agent_cherche_lui_meme_dans_le_projet(lancer_agent):
    """L'outil reçoit l'index ouvert à la première question, avant l'agent."""
    observe = lancer_agent(["Où vérifie-t-on le token de connexion ?"])

    assert "search_codebase" in observe[0]["outils"]
    appel = observe[0]["appel"]
    assert appel.ok, appel.content
    assert "src/auth.py:4-6" in appel.content


def test_sans_rag_l_outil_n_est_pas_propose(lancer_agent):
    observe = lancer_agent(["Où vérifie-t-on le token ?"], rag=False)

    assert "search_codebase" not in observe[0]["outils"]


def test_index_indisponible_l_outil_repond_proprement(lancer_agent):
    """Indexation en échec : la recherche est coupée, l'outil répond sans planter."""
    observe = lancer_agent(["Une question"], embedder=EmbedderEnPanne())

    appel = observe[0]["appel"]
    assert appel is not None and not appel.ok
    assert "indisponible" in appel.content.lower()


def test_l_outil_suit_les_reglages_du_rag(lancer_agent):
    """--rag-min-score s'applique aussi aux recherches de l'agent."""
    observe = lancer_agent(["Où vérifie-t-on le token ?"], rag_min_score=0.99)

    appel = observe[0]["appel"]
    assert "src/auth.py" not in appel.content


def test_l_outil_ignore_la_limite_des_passages_automatiques(lancer_agent, projet):
    """--rag-top-k limite ce qui est ajouté à chaque question, pas les
    recherches demandées par le modèle (essai réel du 2026-10-14)."""
    (projet / "src" / "session.py").write_text(
        "def ouvrir_session(token):\n"
        '    """Ouvre une session à partir du token."""\n'
        "    return {'token': token}\n",
        encoding="utf-8",
    )
    observe = lancer_agent(["Où utilise-t-on le token ?"], rag_top_k=1)

    appel = observe[0]["appel"]
    assert "src/auth.py" in appel.content
    assert "src/session.py" in appel.content


def test_les_garde_fous_masquent_les_secrets_trouves_par_l_outil(lancer_agent, projet):
    """OUT-15 (EV4) : un passage du projet qui contient une clé d'API ne doit
    pas arriver en clair au modèle. Clé factice, au format d'une vraie."""
    (projet / "src" / "reglages.py").write_text(
        "# token de connexion au service\n"
        'API_KEY = "sk-abcdef1234567890abcdef"\n',
        encoding="utf-8",
    )
    observe = lancer_agent(["Où est le token ?"])

    appel = observe[0]["appel"]
    assert "src/reglages.py" in appel.content
    assert "sk-abcdef1234567890abcdef" not in appel.content


def test_un_outil_desactive_dans_la_config_n_est_pas_propose(lancer_agent):
    from sensai.execution.tool_policy import ToolPreferences

    observe = lancer_agent(
        ["Une question"], tool_preferences=ToolPreferences(disabled=frozenset({"web_search"}))
    )

    assert "web_search" not in observe[0]["outils"]
    assert "read_file" in observe[0]["outils"]


def test_les_dossiers_autorises_de_la_config_s_appliquent(lancer_agent, projet):
    """`files.read` limite read_file au dossier choisi (ADR-0011)."""
    from sensai.execution.file_permissions import FilePermissions

    (projet / "docs").mkdir()
    (projet / "docs" / "notes.md").write_text("notes", encoding="utf-8")
    observe = lancer_agent(
        ["Une question"],
        file_permissions=FilePermissions.from_dict({"root": str(projet), "read": ["docs"]}),
        appels=[("read_file", {"path": "docs/notes.md"}), ("read_file", {"path": "src/auth.py"})],
    )

    docs, src = observe[0]["resultats"]
    assert docs.ok
    assert not src.ok


# --- Document d'état du projet (M4, ADR-0029) ---------------------------------


def test_l_agent_peut_mettre_a_jour_le_document_d_etat(lancer_agent):
    observe = lancer_agent(["Une question"])

    assert "update_state" in observe[0]["outils"]


def test_le_document_d_etat_est_dans_le_prompt_systeme(lancer_agent, projet):
    """US-M4-1 : l'agent le connaît dès le premier message, sans le relire."""
    (projet / "SENSAI.md").write_text("## En cours\n\n- R2 : reranking\n", encoding="utf-8")

    observe = lancer_agent(["Où en est-on ?"])

    assert "- R2 : reranking" in observe[0]["systeme"]


def test_le_prompt_suit_la_mise_a_jour_du_document(lancer_agent, projet, monkeypatch):
    """Après une mise à jour acceptée, le tour suivant voit la nouvelle version."""
    reponses = iter([True])
    observe = lancer_agent(
        ["Première", "Seconde"],
        appels=[("update_state", {"section": "En cours", "action": "replace", "content": "- M4"})],
        confirmer=lambda request: next(reponses, False),
    )

    assert "- M4" not in observe[0]["systeme"]
    assert "- M4" in observe[1]["systeme"]


def test_commande_state_affiche_le_document(lancer_agent, projet, capsys):
    (projet / "SENSAI.md").write_text("## Fait\n\n- M1\n", encoding="utf-8")

    lancer_agent(["/state"])

    assert "- M1" in capsys.readouterr().out


# --- Mémoire structurée (M3, ADR-0030) ----------------------------------------


def test_l_agent_peut_retenir_et_retrouver_des_faits(lancer_agent):
    observe = lancer_agent(["Une question"])

    assert {"save_fact", "recall_facts"} <= set(observe[0]["outils"])


def test_un_fait_retenu_est_connu_dans_une_nouvelle_session(lancer_agent):
    """US-M3-1 et 2 : le fait survit à la fermeture du CLI, et l'entité est
    annoncée dans le prompt système de la session suivante."""
    lancer_agent(
        ["Première"],
        appels=[("save_fact", {"entity": "auth", "attribute": "version_redis", "value": "7"})],
        confirmer=lambda request: True,
    )

    observe = lancer_agent(
        ["Quelle version de Redis ?"], new_session=True,
        appels=[("recall_facts", {"entity": "auth"})],
    )

    assert "auth" in observe[0]["systeme"]
    assert "7" in observe[0]["resultats"][0].content


def test_commande_facts(lancer_agent, capsys):
    lancer_agent(
        ["Première"],
        appels=[("save_fact", {"entity": "auth", "attribute": "version_redis", "value": "7"})],
        confirmer=lambda request: True,
    )
    capsys.readouterr()

    lancer_agent(["/facts auth", "/facts forget auth version_redis", "/facts auth"],
                 new_session=True)

    sortie = capsys.readouterr().out
    assert "version_redis" in sortie and "7" in sortie
    assert "Aucun fait" in sortie


def test_les_passages_ajoutes_a_la_question_sont_filtres(lancer, projet):
    """EV2 : les passages que la recherche ajoute d'elle-même à chaque question
    passent par le même filtre que les sorties d'outils. Essai réel du
    2026-10-24 : la clé de reglages.py arrivait en clair au modèle, qui
    l'affichait sans avoir appelé read_file. Clé factice, au format d'une vraie."""
    (projet / "src" / "reglages.py").write_text(
        "# token de connexion au service\n"
        'API_KEY = "sk-abcdef1234567890abcdef"\n',
        encoding="utf-8",
    )
    envoyes, _ = lancer(["Où est le token de connexion ?"])

    question = envoyes[0][-1]["content"]
    assert "src/reglages.py" in question, "le passage part toujours au modèle"
    assert "sk-abcdef1234567890abcdef" not in question


def test_structured_s_appuie_sur_ce_que_l_agent_a_trouve(lancer, projet, monkeypatch):
    """T5 (ADR-0039) : /structured fait d'abord chercher l'agent (ici le faux
    modèle répond « D'accord. »), puis met en forme à partir de sa réponse."""
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

    envoyes, _ = lancer(["/structured schema.json liste les fonctions de src/auth.py"])

    assert envoyes, "l'agent a été appelé pour chercher"
    assert "liste les fonctions de src/auth.py" in envoyes[0][-1]["content"]
    assert vus and "D'accord." in vus[0] and "liste les fonctions" in vus[0]


def test_les_outils_mcp_de_la_config_sont_proposes(lancer_agent, capsys):
    """T1 (ADR-0041) : les outils d'un serveur MCP déclaré dans config.json sont
    proposés à l'agent ; un serveur introuvable n'empêche pas le démarrage."""
    import sys
    from pathlib import Path

    serveur = str(Path(__file__).parent / "tools" / "fake_mcp_server.py")
    observe = lancer_agent(["Additionne 2 et 3."], mcp_servers={
        "faux": {"command": sys.executable, "args": [serveur], "env": {}, "cwd": None,
                 "risk": "execute", "timeout_s": 10.0},
        "absent": {"command": "commande-qui-n-existe-pas-xyz", "args": [], "env": {},
                   "cwd": None, "risk": "execute", "timeout_s": 10.0},
    })

    assert "mcp_faux_add" in observe[0]["outils"]
    assert "absent" in capsys.readouterr().out, "la panne est signalée"
