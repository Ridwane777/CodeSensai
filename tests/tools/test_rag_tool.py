"""
Tests de RagTool : la recherche du RAG exposée comme un outil pour la boucle
ReAct du Lot A (ADR-0002, ADR-0009 décision 4).

Le contrat Tool impose qu'un outil ne lève jamais d'exception :
`test_ollama_indisponible_renvoie_une_erreur_propre` échoue si on laisse
passer une EmbeddingError.
"""
from sensai.core.tools import ToolRegistry
from sensai.execution.gateway import ToolGateway
from sensai.execution.tool_policy import Risk, risk_of
from sensai.knowledge.rag import EmbeddingError, RagIndex
from sensai.tools.rag_tool import RagTool
from tests.knowledge.test_rag import FauxEmbedder


def index_avec_auth(tmp_path):
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / "auth.py").write_text(
        "def verifier_token(token):\n"
        '    """Vérifie le token de connexion."""\n'
        "    return bool(token)\n",
        encoding="utf-8",
    )
    index = RagIndex(tmp_path / "rag.db", project="p", embed=FauxEmbedder())
    index.update(projet)
    return index


def test_trouve_et_cite(tmp_path):
    outil = RagTool(index_avec_auth(tmp_path), min_score=0.0)

    resultat = outil.run(query="vérifie le token de connexion")

    assert resultat.ok
    assert "auth.py:1-3" in resultat.content
    assert resultat.data["passages"][0]["source"] == "auth.py"


def test_rien_trouve_le_dit(tmp_path):
    outil = RagTool(index_avec_auth(tmp_path), min_score=0.5)

    resultat = outil.run(query="broker kafka zookeeper")

    assert resultat.ok
    assert "aucun passage" in resultat.content.lower()
    assert resultat.data["passages"] == []


def test_sans_index():
    assert not RagTool().run(query="token").ok


def test_requete_vide_refusee(tmp_path):
    assert not RagTool(index_avec_auth(tmp_path)).run(query="  ").ok


class EnPanne:
    def __call__(self, textes):
        raise EmbeddingError("Ollama injoignable")


def test_ollama_indisponible_renvoie_une_erreur_propre(tmp_path):
    index = index_avec_auth(tmp_path)
    index.embed = EnPanne()

    resultat = RagTool(index).run(query="token")

    assert not resultat.ok
    assert "Ollama injoignable" in resultat.content


def test_declare_le_risque_lecture():
    """ADR-0013 : sans risque déclaré, la passerelle le traite comme une
    exécution et demanderait une confirmation à chaque recherche."""
    assert risk_of(RagTool()) is Risk.READ


def test_passerelle_l_autorise_sans_confirmation(tmp_path):
    registry = ToolRegistry()
    registry.register(RagTool(index_avec_auth(tmp_path), min_score=0.0))
    demandes = []
    passerelle = ToolGateway(registry, confirm=lambda req: demandes.append(req) or False)

    resultat = passerelle.call("search_codebase", query="token")

    assert resultat.ok
    assert demandes == [], "une recherche ne doit pas demander de confirmation"


def test_resultat_presente_comme_une_recherche_demandee(tmp_path):
    """Essai réel du 2026-10-14 : l'outil renvoyait la consigne des passages
    ajoutés automatiquement (« ignore-les »), qui fait douter le modèle d'une
    recherche qu'il a lui-même demandée."""
    resultat = RagTool(index_avec_auth(tmp_path), min_score=0.0).run(query="token")

    assert "automatiquement" not in resultat.content
    assert "ignore" not in resultat.content
    assert '"token"' in resultat.content


# --- R2 : filtres par type et par dossier (US-R2-2) ---------------------------


def test_les_filtres_sont_proposes_au_modele():
    proprietes = RagTool.parameters["properties"]
    assert proprietes["kind"]["enum"] == ["code", "doc"]
    assert "path" in proprietes


def test_filtre_doc_exclut_le_code(tmp_path):
    outil = RagTool(index_avec_auth(tmp_path), min_score=0.0)
    resultat = outil.run(query="token de connexion", kind="doc")
    assert resultat.ok and resultat.data["passages"] == []


def test_filtre_inconnu_ignore(tmp_path):
    outil = RagTool(index_avec_auth(tmp_path), min_score=0.0)
    resultat = outil.run(query="token de connexion", kind="image")
    assert resultat.data["passages"][0]["source"] == "auth.py"
