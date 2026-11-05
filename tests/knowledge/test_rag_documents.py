"""
Indexation des documents (PDF, Office, EPUB) par le RAG — issue #64, ADR-0034.

Comme LlamaIndex, AnythingLLM ou PrivateGPT, le RAG convertit les documents
à l'indexation. Le convertisseur est simulé ici ; le vrai tourne dans la
sandbox (tests/execution/sandbox/test_document_sandbox.py).

Les tests qui comptent le plus :
- `test_une_question_sans_nommer_le_fichier_trouve_le_document` : c'est le
  but, retrouver l'exigence du sujet sans savoir qu'elle est dans le PDF.
- `test_sans_convertisseur_rien_ne_casse` : sans Docker, on revient au
  comportement de R1 (le document est listé avec un conseil).
"""
import pytest

from sensai.execution.sandbox.document_sandbox import ConversionResult
from sensai.knowledge.rag import RagIndex, scan_files
from tests.knowledge.test_rag import FauxEmbedder

SUJET = """# Contraintes
Le projet doit utiliser docker-compose et répondre sur le port 8080.

# Livrables
Au moins deux user stories par feature.
"""


class FauxConvertisseur:
    def __init__(self, resultat=None):
        self.resultat = resultat or ConversionResult(ok=True, text=SUJET)
        self.appels = []

    def __call__(self, path, extension=None):
        self.appels.append((path.name, extension))
        return self.resultat


@pytest.fixture
def projet(tmp_path):
    racine = tmp_path / "projet"
    racine.mkdir()
    (racine / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (racine / "sujet.pdf").write_bytes(b"%PDF-1.7\n\x00binaire")
    return racine


def index_avec(tmp_path, convertisseur):
    return RagIndex(tmp_path / "rag.db", project="p", embed=FauxEmbedder(),
                    converter=convertisseur)


def test_le_scan_reconnait_les_documents(projet):
    resultat = scan_files(projet)
    assert [p.name for p in resultat.documents] == ["sujet.pdf"]
    assert all(p.name != "sujet.pdf" for p in resultat.files)


def test_une_question_sans_nommer_le_fichier_trouve_le_document(tmp_path, projet):
    index = index_avec(tmp_path, FauxConvertisseur())
    rapport = index.update(projet)
    assert rapport.files_indexed == 2 and rapport.unsupported == []
    passages = index.search("combien de user stories par feature ?", min_score=0.0)
    assert passages[0]["source"] == "sujet.pdf"
    assert "deux user stories" in passages[0]["text"]


def test_le_convertisseur_recoit_l_extension(tmp_path, projet):
    convertisseur = FauxConvertisseur()
    index_avec(tmp_path, convertisseur).update(projet)
    assert convertisseur.appels == [("sujet.pdf", ".pdf")]


def test_un_document_n_est_converti_qu_une_fois(tmp_path, projet):
    convertisseur = FauxConvertisseur()
    index = index_avec(tmp_path, convertisseur)
    index.update(projet)
    index.update(projet)
    assert len(convertisseur.appels) == 1
    (projet / "sujet.pdf").write_bytes(b"%PDF-1.7\n\x00nouvelle version")
    index.update(projet)
    assert len(convertisseur.appels) == 2


def test_l_image_absente_est_signalee_et_reessayee(tmp_path, projet):
    convertisseur = FauxConvertisseur(ConversionResult(ok=False, error="image_missing"))
    index = index_avec(tmp_path, convertisseur)
    rapport = index.update(projet)
    conseils = {p.name: c for p, c in rapport.unsupported}
    assert "docker build -t sensai-docs" in conseils["sujet.pdf"]
    assert rapport.files_indexed == 1
    index.update(projet)
    assert len(convertisseur.appels) == 2, "le document doit être réessayé"


def test_un_pdf_scanne_conseille_l_ocr(tmp_path, projet):
    convertisseur = FauxConvertisseur(ConversionResult(ok=False, error="empty"))
    rapport = index_avec(tmp_path, convertisseur).update(projet)
    assert "ocrmypdf" in dict((p.name, c) for p, c in rapport.unsupported)["sujet.pdf"]


def test_sans_convertisseur_rien_ne_casse(tmp_path, projet):
    rapport = index_avec(tmp_path, None).update(projet)
    conseils = {p.name: c for p, c in rapport.unsupported}
    assert "pdf" in conseils["sujet.pdf"].lower()
    assert rapport.files_indexed == 1


def test_un_document_devenu_illisible_est_retire(tmp_path, projet):
    index = index_avec(tmp_path, FauxConvertisseur())
    index.update(projet)
    index.converter = FauxConvertisseur(ConversionResult(ok=False, error="failed"))
    (projet / "sujet.pdf").write_bytes(b"%PDF-1.7\n\x00abime")
    index.update(projet)
    sources = {h["source"] for h in index.search("user stories", min_score=0.0)}
    assert "sujet.pdf" not in sources, "un texte périmé ne doit pas rester cité"
