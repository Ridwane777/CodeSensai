"""
Le budget de tokens (M2, ADR-0045) et `num_ctx` dans le serveur web.

Le CLI les avait, le web non (revue PR #97) : une fonction activée par défaut
d'un côté et absente de l'autre contredisait ADR-0035 (« le même agent des deux
côtés »). On teste ici `WebRuntime` directement, sans serveur HTTP ni Ollama.
"""
import threading

import pytest

pytest.importorskip("fastapi")

from sensai.core.events import Done, Token
from sensai.core.ollama_client import OllamaError
from sensai.knowledge import compression
from sensai.tools import delegate_tool
from sensai.web import runtime as runtime_module
from sensai.web.runtime import WebRuntime
from tests.knowledge.test_rag import FauxEmbedder


class FauxTour:
    """Remplace la boucle d'agent : note les messages reçus et répond « ok »."""

    def __init__(self):
        self.messages = []

    def __call__(self, host, model, messages, tools):
        self.messages.append([dict(m) for m in messages])
        yield Token("ok")
        yield Done("final_answer")


@pytest.fixture
def fabrique(tmp_path):
    def _fabrique(**options):
        projet = tmp_path / "projet"
        projet.mkdir(exist_ok=True)
        settings = {
            "model": "faux-modele",
            "host": "http://127.0.0.1:1",
            "system_prompt": "Tu es CodeSensei.",
            "memory_prompt": "Conversation reprise.",
            "data_dir": str(tmp_path / "donnees"),
            "retention_days": 30,
            "rag": False,
            "rag_model": "bge-m3",
            "rag_min_score": 0.0,
            "rag_top_k": 3,
            "rag_rerank": False,
            "cache": False,
        }
        settings.update(options)
        tour = FauxTour()
        runtime = WebRuntime(settings, projet, run_turn=tour,
                             embedder_factory=lambda host, model: FauxEmbedder(),
                             converter_factory=lambda: None, reranker_factory=None)
        return runtime, tour

    return _fabrique


def jouer(runtime, turns, texte):
    evenements = []
    nouveaux = runtime.run_turn(turns, texte, evenements.append, threading.Event(),
                                lambda demande: True)
    return nouveaux, evenements


def historique(n_paires):
    turns = []
    for i in range(n_paires):
        turns += [{"role": "user", "content": f"question numéro {i} avec un peu de texte"},
                  {"role": "assistant", "content": f"réponse numéro {i} avec un peu de texte"}]
    return turns


def test_num_ctx_part_avec_la_boucle_d_agent_par_defaut(tmp_path, monkeypatch):
    vus = []

    def faux_agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
        vus.append(num_ctx)
        yield Token("ok")
        yield Done("final_answer")

    monkeypatch.setattr(runtime_module, "run_agent_turn", faux_agent)
    projet = tmp_path / "projet"
    projet.mkdir()
    runtime = WebRuntime(
        {"model": "m", "host": "http://h", "rag": False, "rag_model": "bge-m3",
         "rag_min_score": 0.0, "data_dir": str(tmp_path / "d"), "retention_days": 30,
         "num_ctx": 4096},
        projet, embedder_factory=lambda host, model: FauxEmbedder(),
        converter_factory=lambda: None, reranker_factory=None)

    jouer(runtime, [], "Bonjour")

    assert vus == [4096]


def test_les_sous_agents_du_web_recoivent_num_ctx(fabrique, monkeypatch):
    vus = []

    def faux_agent(host, model, messages, tools, num_ctx=None, max_iterations=None):
        vus.append(num_ctx)
        yield Token("ok")
        yield Done("final_answer")

    monkeypatch.setattr(delegate_tool, "_run_agent_turn", faux_agent)
    runtime, _ = fabrique(num_ctx=4096)

    gateway = runtime.make_gateway(lambda demande: True)
    gateway.registry.get("delegate_task").delegate("une sous-tâche")

    assert vus == [4096]


def test_au_dessus_du_budget_les_vieux_tours_sont_resumes(fabrique, monkeypatch):
    appels = []

    def faux_resume(host, model, messages, options=None):
        appels.append(options)
        yield {"content": "voici le résumé"}

    monkeypatch.setattr(compression, "stream_chat_messages", faux_resume)
    runtime, tour = fabrique(token_budget_max=50, token_budget_keep_recent=2, num_ctx=4096)
    turns = historique(10)

    nouveaux, _ = jouer(runtime, turns, "une nouvelle question")

    envoyes = tour.messages[0]
    assert "voici le résumé" in envoyes[0]["content"]
    assert len(envoyes) < len(turns)  # les vieux tours ne partent plus
    assert appels == [{"num_ctx": 4096}]  # le résumé lui-même envoie num_ctx
    # La session sauvegardée (M1) garde tout, intact.
    assert nouveaux[:len(turns)] == turns
    assert nouveaux[-2]["content"] == "une nouvelle question"


def test_token_budget_desactive_ne_resume_rien(fabrique, monkeypatch):
    monkeypatch.setattr(compression, "stream_chat_messages",
                        lambda *a, **k: pytest.fail("ne doit pas résumer"))
    runtime, tour = fabrique(token_budget=False, token_budget_max=50)
    turns = historique(10)

    jouer(runtime, turns, "une nouvelle question")

    assert len(tour.messages[0]) == 1 + len(turns) + 1


def test_echec_du_resume_garde_l_historique_et_avertit_une_fois(fabrique, monkeypatch):
    def en_panne(host, model, messages, options=None):
        raise OllamaError("injoignable")
        yield  # pragma: no cover

    monkeypatch.setattr(compression, "stream_chat_messages", en_panne)
    runtime, tour = fabrique(token_budget_max=50, token_budget_keep_recent=2)
    turns = historique(10)

    jouer(runtime, turns, "première")
    jouer(runtime, turns, "seconde")

    assert len(tour.messages[0]) == 1 + len(turns) + 1  # rien n'est perdu
    avertissements = [n for n in runtime.notices if "Résumé automatique" in n]
    assert len(avertissements) == 1  # pas répété à chaque tour


def test_un_contexte_trop_gros_pour_etre_reduit_avertit(fabrique, monkeypatch):
    """Revue PR #97 : un dernier message gonflé à lui seul au-delà du budget part
    tel quel ; au moins on prévient que la fenêtre risque d'être tronquée."""
    monkeypatch.setattr(compression, "stream_chat_messages",
                        lambda *a, **k: pytest.fail("rien à résumer"))
    runtime, tour = fabrique(token_budget_max=50)

    jouer(runtime, [], "x" * 5000)

    assert any("dépasse le budget" in n for n in runtime.notices)
    assert tour.messages[0][-1]["content"] == "x" * 5000  # envoyé tel quel
