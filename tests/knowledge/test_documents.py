"""
File format identification - issue #64 (ADR-0034, levels 1 and 4).

The test that matters most: `test_an_unknown_format_is_named_without_inventing_anything`.
It replaces "binary?": the agent knows what the file is and what to do.
"""
import zipfile

import pytest

from sensai.knowledge.documents import CONVERTIBLE, identify, unreadable_message


def zip_with(path, *names):
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, "x")
    return path


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "requirements.pdf").write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n")
    zip_with(tmp_path / "spec.docx", "[Content_Types].xml", "word/document.xml")
    zip_with(tmp_path / "budget.xlsx", "[Content_Types].xml", "xl/workbook.xml")
    zip_with(tmp_path / "slides.pptx", "[Content_Types].xml", "ppt/presentation.xml")
    zip_with(tmp_path / "book.epub", "mimetype", "OEBPS/content.opf")
    zip_with(tmp_path / "archive.zip", "a.txt", "b.txt")
    (tmp_path / "logo.png").write_bytes(
        bytes.fromhex("89504e470d0a1a0a0000000d49484452") + bytes(64))
    (tmp_path / "plan.dwg").write_bytes(b"AC1032" + bytes(200))
    (tmp_path / "data.bin").write_bytes(bytes(range(256)) * 4)
    return tmp_path


@pytest.mark.parametrize("name, expected", [
    ("requirements.pdf", "pdf"),
    ("spec.docx", "docx"),
    ("budget.xlsx", "xlsx"),
    ("slides.pptx", "pptx"),
    ("book.epub", "epub"),
    ("archive.zip", "zip"),
    ("logo.png", "image"),
])
def test_type_comes_from_content(folder, name, expected):
    assert identify(folder / name).kind == expected


def test_extension_does_not_fool_it(folder):
    fake = folder / "notes.txt"
    fake.write_bytes((folder / "requirements.pdf").read_bytes())
    assert identify(fake).kind == "pdf"


def test_office_formats_are_convertible():
    assert {"pdf", "docx", "xlsx", "pptx", "epub"} <= CONVERTIBLE
    assert "image" not in CONVERTIBLE


def test_an_unknown_format_is_named_without_inventing_anything(folder):
    message = unreadable_message(folder / "plan.dwg", identify(folder / "plan.dwg"))
    assert "plan.dwg" in message and "AutoCAD" in message
    # Measured: puremagic reports image/x-dwg, but a CAD drawing is not a photo.
    assert identify(folder / "plan.dwg").kind == "other" and "OCR" not in message
    assert "bytes" in message
    assert "do not guess" in message.lower()


def test_binary_data_without_known_type(folder):
    file = folder / "data.bin"
    message = unreadable_message(file, identify(file))
    assert "data.bin" in message and "binary" in message.lower()


def test_an_image_explains_the_model_cannot_see_images(folder):
    message = unreadable_message(folder / "logo.png", identify(folder / "logo.png"))
    assert "image" in message.lower() and "OCR" in message


def test_an_empty_pdf_suggests_ocr(folder):
    file = folder / "requirements.pdf"
    message = unreadable_message(file, identify(file), reason="empty")
    assert "ocrmypdf" in message


def test_missing_conversion_image_gives_the_command(folder):
    file = folder / "requirements.pdf"
    message = unreadable_message(file, identify(file), reason="image_missing")
    assert "docker build -t sensai-docs" in message
    assert "pdftotext" in message
