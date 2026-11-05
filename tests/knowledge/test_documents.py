"""
Identification des formats de fichier — issue #64 (ADR-0034, niveaux 1 et 4).

Le test qui compte le plus : `test_un_format_inconnu_est_nomme_sans_rien_inventer`.
C'est ce qui remplace « binary? » : l'agent sait ce qu'est le fichier et quoi faire.
"""
import zipfile

import pytest

from sensai.knowledge.documents import CONVERTIBLE, identify, unreadable_message


def zip_avec(path, *noms):
    with zipfile.ZipFile(path, "w") as z:
        for nom in noms:
            z.writestr(nom, "x")
    return path


@pytest.fixture
def dossier(tmp_path):
    (tmp_path / "sujet.pdf").write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n")
    zip_avec(tmp_path / "cahier.docx", "[Content_Types].xml", "word/document.xml")
    zip_avec(tmp_path / "budget.xlsx", "[Content_Types].xml", "xl/workbook.xml")
    zip_avec(tmp_path / "slides.pptx", "[Content_Types].xml", "ppt/presentation.xml")
    zip_avec(tmp_path / "livre.epub", "mimetype", "OEBPS/content.opf")
    zip_avec(tmp_path / "archive.zip", "a.txt", "b.txt")
    (tmp_path / "logo.png").write_bytes(
        bytes.fromhex("89504e470d0a1a0a0000000d49484452") + bytes(64))
    (tmp_path / "plan.dwg").write_bytes(b"AC1032" + bytes(200))
    (tmp_path / "donnees.bin").write_bytes(bytes(range(256)) * 4)
    return tmp_path


@pytest.mark.parametrize("nom, attendu", [
    ("sujet.pdf", "pdf"),
    ("cahier.docx", "docx"),
    ("budget.xlsx", "xlsx"),
    ("slides.pptx", "pptx"),
    ("livre.epub", "epub"),
    ("archive.zip", "zip"),
    ("logo.png", "image"),
])
def test_le_type_vient_du_contenu(dossier, nom, attendu):
    assert identify(dossier / nom).kind == attendu


def test_l_extension_ne_trompe_pas(dossier):
    faux = dossier / "notes.txt"
    faux.write_bytes((dossier / "sujet.pdf").read_bytes())
    assert identify(faux).kind == "pdf"


def test_les_formats_bureautiques_sont_convertibles():
    assert {"pdf", "docx", "xlsx", "pptx", "epub"} <= CONVERTIBLE
    assert "image" not in CONVERTIBLE


def test_un_format_inconnu_est_nomme_sans_rien_inventer(dossier):
    message = unreadable_message(dossier / "plan.dwg", identify(dossier / "plan.dwg"))
    assert "plan.dwg" in message and "AutoCAD" in message
    # Mesuré : puremagic donne image/x-dwg, mais un dessin CAO n'est pas une photo.
    assert identify(dossier / "plan.dwg").kind == "other" and "OCR" not in message
    assert "bytes" in message
    assert "do not guess" in message.lower()


def test_donnees_binaires_sans_type_connu(dossier):
    fichier = dossier / "donnees.bin"
    message = unreadable_message(fichier, identify(fichier))
    assert "donnees.bin" in message and "binary" in message.lower()


def test_une_image_explique_que_le_modele_ne_voit_pas_les_images(dossier):
    message = unreadable_message(dossier / "logo.png", identify(dossier / "logo.png"))
    assert "image" in message.lower() and "OCR" in message


def test_un_pdf_vide_conseille_l_ocr(dossier):
    fichier = dossier / "sujet.pdf"
    message = unreadable_message(fichier, identify(fichier), reason="empty")
    assert "ocrmypdf" in message


def test_image_de_conversion_absente_donne_la_commande(dossier):
    fichier = dossier / "sujet.pdf"
    message = unreadable_message(fichier, identify(fichier), reason="image_missing")
    assert "docker build -t sensai-docs" in message
    assert "pdftotext" in message
