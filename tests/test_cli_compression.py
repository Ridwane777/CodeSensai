"""
Teste M2 (budget de tokens, résumé glissant) de bout en bout sur le vrai
CLI, sans Ollama.

Même patron que `tests/test_cli_rag.py` : un faux `stream_chat` note les
messages reçus par la boucle de chat ; `compression.stream_chat_messages`
est aussi remplacé, pour le résumé.
"""
import builtins

import pytest

from sensai import cli
from sensai.knowledge import compression
from sensai.knowledge.memory import SESSIONS_FILE, SessionStore
from tests.test_cli_rag import lancer as lancer_avec_rag  # noqa: F401  (fixture)
from tests.test_cli_rag import projet  # noqa: F401  (fixture)


@pytest.fixture
def lancer(tmp_path, monkeypatch):
    def _lancer(entrees, *, resume="résumé automatique", **options):
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
        settings.update(options)
        envoyes = []
        options_recus = []

        def faux_stream_chat(host, model, messages):
            envoyes.append([dict(m) for m in messages])
            yield "D'accord."

        def faux_stream_chat_messages(host, model, messages, options=None):
            options_recus.append(options)
            yield {"content": resume}

        restantes = iter(entrees)

        def faux_input(_prompt=""):
            try:
                return next(restantes)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        monkeypatch.setattr(cli, "stream_chat", faux_stream_chat)
        monkeypatch.setattr(compression, "stream_chat_messages", faux_stream_chat_messages)
        monkeypatch.setattr(builtins, "input", faux_input)
        cli.main()
        _lancer.options_recus = options_recus
        return envoyes

    return _lancer


def test_sous_le_budget_lhistorique_part_entier(lancer):
    envoyes = lancer(["première question", "deuxième question"])

    # Deuxième tour : system + 2 tours précédents + la nouvelle question.
    assert len(envoyes[1]) == 4
    assert envoyes[1][1]["content"] == "première question"


def test_au_dessus_du_budget_les_tours_anciens_sont_resumes(lancer):
    questions = [f"question numéro {i} avec un peu de texte pour peser" for i in range(10)]
    envoyes = lancer(questions, token_budget_max=50, token_budget_keep_recent=2,
                      resume="voici le résumé des échanges précédents")

    dernier = envoyes[-1]
    # system + résumé + (keep_recent=2 tours anciens à partir du dernier
    # tour complet) + la question du tour courant, encore non ajoutée côté
    # assistant : au moins le résumé doit remplacer le tout-venant.
    contenu = " ".join(m["content"] for m in dernier)
    assert "voici le résumé des échanges précédents" in contenu
    assert "question numéro 0" not in contenu  # la plus ancienne a été résumée


def test_lhistorique_sauvegarde_reste_intact_malgre_la_compression(lancer, tmp_path):
    questions = [f"question numéro {i} avec un peu de texte pour peser" for i in range(10)]
    lancer(questions, token_budget_max=50, token_budget_keep_recent=2)

    store = SessionStore(tmp_path / "donnees" / SESSIONS_FILE)
    turns = store.load(store.list()[0].id)
    # Rien n'est résumé en base : chaque question posée s'y retrouve en entier.
    questions_sauvees = [t["content"] for t in turns if t["role"] == "user"]
    assert questions_sauvees == questions


def test_no_token_budget_desactive_le_resume(lancer):
    questions = [f"question numéro {i} avec un peu de texte pour peser" for i in range(10)]
    envoyes = lancer(questions, token_budget=False, token_budget_max=50)

    contenu = " ".join(m["content"] for m in envoyes[-1])
    assert "question numéro 0" in contenu  # jamais résumée : le budget est désactivé


def test_resume_vide_garde_les_tours_bruts(lancer, capsys):
    questions = [f"question numéro {i} avec un peu de texte pour peser" for i in range(10)]
    envoyes = lancer(questions, token_budget_max=50, token_budget_keep_recent=2, resume="")

    # resume="" fait lever CompressionError (résumé vide) : les tours restent bruts.
    contenu = " ".join(m["content"] for m in envoyes[-1])
    assert "question numéro 0" in contenu
    assert "résumé automatique de l'historique impossible" in capsys.readouterr().out


def test_num_ctx_est_transmis_a_lappel_de_resume(lancer):
    """Revue PR #97 : sans num_ctx, Ollama tronque en silence avant que le
    budget n'ait eu l'occasion d'agir — il doit partir avec l'appel."""
    questions = [f"question numéro {i} avec un peu de texte pour peser" for i in range(10)]
    lancer(
        questions, token_budget_max=50, token_budget_keep_recent=2, num_ctx=4096,
        resume="résumé",
    )
    assert {"num_ctx": 4096} in lancer.options_recus


def test_le_contexte_rag_compte_dans_le_budget(lancer_avec_rag, projet):  # noqa: F811
    """Revue PR #97 : la compression doit s'appliquer APRÈS avoir ajouté le
    RAG à la question, sinon le budget ignore ce qui part vraiment."""
    resume_vu = []

    def faux_stream_chat_messages(host, model, messages, options=None):
        resume_vu.append(True)
        yield {"content": "résumé des échanges"}

    import sensai.knowledge.compression as compression_module
    original = compression_module.stream_chat_messages
    try:
        compression_module.stream_chat_messages = faux_stream_chat_messages
        # Une question courte, répétée : seule, elle resterait sous un petit
        # budget ; avec le passage RAG ajouté (src/auth.py), elle le dépasse.
        questions = [f"q{i}" for i in range(8)]
        _envoyes, _ = lancer_avec_rag(
            questions, token_budget=True, token_budget_max=80, token_budget_keep_recent=2,
        )
        assert resume_vu, "le budget doit se déclencher une fois le contexte RAG ajouté"
    finally:
        compression_module.stream_chat_messages = original


# --- num_ctx sur tous les chemins vers Ollama (revue PR #97) -----------------------


def test_les_sous_agents_recoivent_num_ctx(lancer, monkeypatch):
    """`delegate_task` / `team_task` restaient soumis à la troncature par défaut
    d'Ollama alors que la boucle principale envoyait `num_ctx`."""
    from sensai.core.events import Done, Token
    from sensai.tools import delegate_tool

    recus = []

    def faux_tour(host, model, messages, tools, num_ctx=None):
        recus.append(num_ctx)
        yield Token(text="ok")
        yield Done()

    instances = []

    class DelegateEspion(cli.DelegateTool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(delegate_tool, "_run_agent_turn", faux_tour)
    monkeypatch.setattr(cli, "DelegateTool", DelegateEspion)
    lancer(["Bonjour"], num_ctx=4096)

    instances[0].delegate("une sous-tâche")

    assert recus == [4096]


def test_structured_recoit_num_ctx(lancer, monkeypatch):
    vus = []

    def espion(line, **kwargs):
        vus.append(kwargs.get("num_ctx"))
        return "{}" if line.startswith("/structured") else None

    monkeypatch.setattr(cli, "handle_structured_command", espion)
    lancer(["/structured schema.json fais X"], num_ctx=4096)
    assert vus == [4096]


def test_le_prechauffage_du_modele_envoie_num_ctx(monkeypatch):
    """Ollama recharge le modèle si la fenêtre d'une requête diffère de celle du
    chargement : on préchauffe avec la même."""
    envoyes = []

    class Reponse:
        def raise_for_status(self):
            pass

    def faux_post(url, json=None, timeout=None):
        envoyes.append((url, json))
        return Reponse()

    monkeypatch.setattr(cli.requests, "post", faux_post)
    cli.preload_model("http://h", "m", num_ctx=4096)
    cli.preload_model("http://h", "m")

    assert envoyes[0][1] == {"model": "m", "prompt": "", "options": {"num_ctx": 4096}}
    assert envoyes[1][1] == {"model": "m", "prompt": ""}


def test_un_message_trop_gros_pour_etre_resume_avertit(lancer, capsys):
    """Revue PR #97 : rien à résumer, le message part tel quel — mais l'utilisateur
    doit le savoir, pas découvrir une réponse bâtie sur un contexte tronqué."""
    envoyes = lancer(["x" * 5000], token_budget_max=50)

    assert envoyes[0][-1]["content"] == "x" * 5000  # envoyé tel quel
    assert "dépasse le budget" in capsys.readouterr().out


def test_le_rag_seul_peut_depasser_le_budget_et_avertit(lancer_avec_rag, projet, capsys):  # noqa: F811
    """Une question courte, mais gonflée par un passage du projet."""
    lancer_avec_rag(["token"], token_budget=True, token_budget_max=20)
    assert "dépasse le budget" in capsys.readouterr().out


def test_sous_le_budget_aucun_avertissement(lancer, capsys):
    lancer(["bonjour"], token_budget_max=5000)
    assert "dépasse le budget" not in capsys.readouterr().out


def test_describe_context_montre_le_prompt_exact_et_les_reglages():
    """/context montre le prompt exact envoyé (ADR-0058)."""
    from sensai.core.context_view import describe_context

    out = describe_context(
        [{"role": "system", "content": "Tu es CodeSensei."}, {"role": "user", "content": "salut"}],
        8192, 6192, {"temperature": 0.2, "top_p": 0.9})
    assert "2 message(s)" in out and "num_ctx=8192" in out and "budget=6192" in out
    assert "temperature=0.2, top_p=0.9" in out
    assert "--- [1] system" in out and "Tu es CodeSensei." in out and "salut" in out
