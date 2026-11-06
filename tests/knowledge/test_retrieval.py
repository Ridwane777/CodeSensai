"""
Tests du RAG avancé — feature [R2].

Chaque bloc renvoie à une user story de docs/user-stories/R2-advanced-rag.md ;
les choix testés viennent de docs/decisions/0032-rag-hybride-et-reclassement.md.

Les tests qui comptent le plus :
- `test_un_nom_exact_remonte_grace_a_bm25` : c'est le défaut de R1 que
  la recherche hybride corrige.
- `test_reclassement_rate_garde_l_ordre_de_la_fusion` : un modèle qui répond
  mal ne doit jamais casser la recherche.
- `test_le_seuil_s_applique_aussi_aux_passages_de_bm25` : sans cela, un mot
  commun ferait remonter un passage hors sujet et l'agent inventerait (US-R2-3).
"""
import json

import pytest
import requests

from sensai.knowledge.rag import RagIndex
from sensai.knowledge.retrieval import (
    BM25,
    LlmReranker,
    reciprocal_rank_fusion,
    tokenize,
)
from tests.knowledge.test_rag import FauxEmbedder

# --- Briques : mots, BM25, fusion ---------------------------------------------


def test_tokenize_decoupe_les_noms_du_code():
    assert tokenize("retention_days") == ["retention_days", "retention", "days"]
    assert "store" in tokenize("FactStore")
    assert "factstore" in tokenize("FactStore")


def test_tokenize_ignore_accents_et_mots_vides():
    assert tokenize("Où sont stockés les faits ?") == ["stockes", "faits"]


def test_bm25_prefere_le_document_qui_contient_le_mot_rare():
    bm25 = BM25(["le projet utilise python", "FactStore garde les faits", "python python"])
    assert bm25.search("FactStore", top_k=3)[0][0] == 1


def test_bm25_ignore_les_documents_sans_mot_commun():
    assert BM25(["alpha", "beta"]).search("gamma", top_k=5) == []


def test_rrf_favorise_l_accord_des_deux_classements():
    dense = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    mots = [{"id": "d"}, {"id": "b"}, {"id": "e"}]
    fusion = reciprocal_rank_fusion([dense, mots], key=lambda h: h["id"])
    assert fusion[0]["id"] == "b"  # 2e partout bat 1er d'un seul côté
    assert {h["id"] for h in fusion} == {"a", "b", "c", "d", "e"}


# --- US-R2-1 : reclassement par le modèle -------------------------------------


class FausseReponse:
    def __init__(self, contenu):
        self.contenu = contenu

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self.contenu}}


def passages(n):
    return [{"source": f"f{i}.py", "start": 1, "end": 2, "text": f"texte {i}"} for i in range(n)]


def test_le_modele_reordonne_les_premiers(monkeypatch):
    envoye = {}

    def post(url, json, timeout):
        envoye.update(json)
        return FausseReponse('{"ordre": [2, 0]}')

    monkeypatch.setattr(requests, "post", post)
    ordre = LlmReranker("http://h", "m", depth=3)("question", passages(4))
    assert [p["source"] for p in ordre] == ["f2.py", "f0.py", "f1.py", "f3.py"]
    assert envoye["format"] == "json" and "question" in envoye["messages"][0]["content"]


@pytest.mark.parametrize("contenu", ["pas du json", '{"ordre": "x"}', '{"autre": [1]}'])
def test_reclassement_rate_garde_l_ordre_de_la_fusion(monkeypatch, contenu):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FausseReponse(contenu))
    ordre = LlmReranker("http://h", "m")("q", passages(3))
    assert [p["source"] for p in ordre] == ["f0.py", "f1.py", "f2.py"]


def test_modele_injoignable_garde_l_ordre(monkeypatch):
    def panne(*a, **k):
        raise requests.ConnectionError("Ollama éteint")

    monkeypatch.setattr(requests, "post", panne)
    assert LlmReranker("http://h", "m")("q", passages(2)) == passages(2)


def test_numeros_inventes_ou_doubles_ignores(monkeypatch):
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: FausseReponse(json.dumps({"ordre": [1, 1, 9, -1]})))
    ordre = LlmReranker("http://h", "m")("q", passages(3))
    assert [p["source"] for p in ordre] == ["f1.py", "f0.py", "f2.py"]


def test_un_seul_passage_n_appelle_pas_le_modele(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("appel inutile"))
    assert LlmReranker("http://h", "m")("q", passages(1)) == passages(1)


# --- Recherche hybride dans l'index -------------------------------------------


@pytest.fixture
def index(tmp_path):
    racine = tmp_path / "projet"
    (racine / "src").mkdir(parents=True)
    (racine / "docs").mkdir()
    (racine / "src" / "store.py").write_text(
        "class FactStore:\n    def remember(self, entite, valeur):\n        return valeur\n",
        encoding="utf-8")
    (racine / "src" / "auth.py").write_text(
        "def verifier_token(token):\n    return bool(token)\n", encoding="utf-8")
    (racine / "docs" / "faits.md").write_text(
        "# Faits\nLes faits retenus par l'agent sur le projet.\n", encoding="utf-8")
    idx = RagIndex(tmp_path / "rag.db", project="p", embed=FauxEmbedder())
    idx.update(racine)
    return idx


def test_un_nom_exact_remonte_grace_a_bm25(index):
    resultats = index.search("FactStore", min_score=0.0)
    assert resultats[0]["source"] == "src/store.py"


def test_chaque_passage_garde_son_score_de_similarite(index):
    for hit in index.search("faits retenus", min_score=0.0):
        assert 0.0 <= hit["score"] <= 1.0


def test_le_seuil_s_applique_aussi_aux_passages_de_bm25(index):
    # « token » est un mot exact de auth.py, mais la question entière en est loin.
    assert index.search("token kafka zookeeper broker partition", min_score=0.6) == []


def test_le_reclasseur_recoit_les_candidats(index):
    vus = []

    def reclasseur(question, hits):
        vus.append(question)
        return list(reversed(hits))

    index.reranker = reclasseur
    normal = index.search("faits du projet", min_score=0.0, rerank=False)
    reclasse = index.search("faits du projet", min_score=0.0)
    assert vus == ["faits du projet"]
    assert reclasse[0] != normal[0] or len(normal) == 1


# --- US-R2-2 : filtres par type et par dossier --------------------------------


def test_filtre_code(index):
    assert {h["source"] for h in index.search("faits", min_score=0.0, kind="code")} <= {
        "src/store.py", "src/auth.py"}


def test_filtre_doc(index):
    sources = {h["source"] for h in index.search("faits", min_score=0.0, kind="doc")}
    assert sources == {"docs/faits.md"}


def test_filtre_dossier(index):
    sources = {h["source"] for h in index.search("faits token", min_score=0.0, path="src")}
    assert sources and all(s.startswith("src/") for s in sources)


def test_filtre_dossier_ne_confond_pas_les_prefixes(index):
    assert index.search("faits", min_score=0.0, path="sr") == []


def test_le_reclassement_envoie_num_ctx_quand_il_est_donne(monkeypatch):
    """Revue PR #97 : le prompt de reclassement colle jusqu'à `depth` passages ;
    sans num_ctx, Ollama peut le tronquer en silence."""
    envoye = {}

    def post(url, json, timeout):
        envoye.update(json)
        return FausseReponse('{"ordre": [0, 1]}')

    monkeypatch.setattr(requests, "post", post)
    LlmReranker("http://h", "m", num_ctx=4096)("question", passages(3))
    # Température 0 en plus : le classement doit être reproductible (ADR-0057).
    assert envoye["options"] == {"temperature": 0, "num_ctx": 4096}

    envoye.clear()
    LlmReranker("http://h", "m")("question", passages(3))
    assert envoye["options"] == {"temperature": 0}
