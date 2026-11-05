"""
[Lot C — Ridwane] Reconnaître le format d'un fichier et dire comment le lire — issue #64.

ADR-0034, niveaux 1 et 4 : le type vient du contenu (octets magiques), pas de
l'extension. Un format de document connu (`CONVERTIBLE`) est converti en
texte dans la sandbox (`execution/sandbox/document_sandbox.py`) ; pour tout le
reste, `unreadable_message` nomme le type et donne la marche à suivre, pour
que le modèle n'invente jamais le contenu.

Les messages sont en anglais, comme le reste de ce que `read_file` renvoie au
modèle.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

import puremagic

# Formats que MarkItDown convertit en texte (extras installés dans l'image
# sensai-docs : docker/docs/Dockerfile).
CONVERTIBLE = frozenset({"pdf", "docx", "pptx", "xlsx", "xls", "msg", "epub", "zip"})

LABELS = {
    "pdf": "PDF",
    "docx": "Word document",
    "pptx": "PowerPoint presentation",
    "xlsx": "Excel workbook",
    "xls": "Excel 97-2003 workbook",
    "msg": "Outlook message",
    "epub": "EPUB book",
    "zip": "ZIP archive",
    "doc": "Word 97-2003 document",
    "ppt": "PowerPoint 97-2003 presentation",
}

# Extension donnée au fichier dans le conteneur : MarkItDown s'en sert pour
# choisir son convertisseur.
EXTENSIONS = {kind: f".{kind}" for kind in CONVERTIBLE}

# Marche à suivre sans le convertisseur, par type.
MANUAL = {
    "pdf": "convert it with `pdftotext {name} {stem}.txt` (poppler-utils), then read {stem}.txt",
    "docx": "convert it with `pandoc {name} -o {stem}.md`, or save it as .txt",
    "doc": "save it as .docx or .txt (`libreoffice --headless --convert-to docx {name}`)",
    "pptx": "export it as PDF or text from the presentation software",
    "ppt": "save it as .pptx or PDF from the presentation software",
    "xlsx": "export each sheet as CSV from the spreadsheet software",
    "xls": "export each sheet as CSV from the spreadsheet software",
    "msg": "save the message as .txt or .eml from the mail client",
    "epub": "convert it with `pandoc {name} -o {stem}.md`",
    "zip": "extract it (`unzip {name}`) and read the files inside",
}

# Images matricielles : celles qu'un OCR peut lire. puremagic range aussi des
# dessins vectoriels ou CAO sous image/ (AutoCAD : image/x-dwg).
RASTER_IMAGES = frozenset({"image/png", "image/jpeg", "image/gif", "image/bmp",
                           "image/tiff", "image/webp"})

_OLE = bytes.fromhex("d0cf11e0a1b11ae1")  # conteneur des formats Office 97-2003 et .msg
_OLE_KINDS = {".xls": "xls", ".msg": "msg", ".doc": "doc", ".ppt": "ppt"}


@dataclass(frozen=True)
class FileKind:
    kind: str    # "pdf", "docx", …, "image", "audio", "video", "other" ou "unknown"
    label: str   # description lisible : « PDF », « Generic AutoCAD drawing »
    mime: str = ""


def _zip_kind(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return "zip"
    if "mimetype" in names and any(n.endswith(".opf") for n in names):
        return "epub"
    for prefix, kind in (("word/", "docx"), ("xl/", "xlsx"), ("ppt/", "pptx")):
        if any(n.startswith(prefix) for n in names):
            return kind
    return "zip"


def identify(path: Path) -> FileKind:
    """Le type de `path`, d'après ses premiers octets (et la liste d'une archive ZIP)."""
    with open(path, "rb") as handle:
        head = handle.read(8192)
    if head.startswith(b"%PDF-"):
        return FileKind("pdf", LABELS["pdf"], "application/pdf")
    if head.startswith(b"PK\x03\x04") and zipfile.is_zipfile(path):
        kind = _zip_kind(path)
        return FileKind(kind, LABELS[kind])
    if head.startswith(_OLE):
        kind = _OLE_KINDS.get(path.suffix.lower())
        if kind:
            return FileKind(kind, LABELS[kind])
        return FileKind("other", "Microsoft Office 97-2003 / OLE file")
    try:
        match = puremagic.magic_string(head)[0] if head else None
    except (puremagic.PureError, ValueError, IndexError):
        match = None
    if match is None or match.mime_type == "application/octet-stream" or not match.name:
        return FileKind("unknown", "binary data of unknown format")
    mime = match.mime_type or ""
    family = mime.split("/")[0]
    if family in ("audio", "video"):
        kind = family
    else:
        kind = "image" if mime in RASTER_IMAGES else "other"
    return FileKind(kind, match.name, match.mime_type or "")


def looks_binary(path: Path) -> bool:
    """Un octet nul dans les 8 premiers Ko : du binaire, même s'il se décode en
    UTF-8 (critère de Git)."""
    with open(path, "rb") as handle:
        return b"\x00" in handle.read(8192)


def unreadable_message(path: Path, kind: FileKind, reason: str | None = None) -> str:
    """Ce que le modèle reçoit quand il ne peut pas lire le contenu (niveau 4).

    `reason` : pourquoi la conversion n'a pas donné de texte (`image_missing`,
    `empty`, `timeout`…), ou None si le format n'est pas convertible.
    """
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    head = f"{path.name}: {kind.label} ({size} bytes)."
    manual = MANUAL.get(kind.kind, "").format(name=path.name, stem=path.stem)
    if reason == "image_missing":
        body = ("It can be converted to text, but the converter image is not built: run "
                "`docker build -t sensai-docs:latest docker/docs` (ADR-0034).")
        if manual:
            body += f" Without it: {manual}."
    elif reason == "empty" and kind.kind == "pdf":
        body = ("It has no text layer (probably scanned). Run OCR first: "
                f"`ocrmypdf {path.name} {path.stem}-ocr.pdf`, then read the new file.")
    elif reason == "empty":
        body = "It contains no text."
    elif reason:
        body = f"Conversion to text failed ({reason})."
        if manual:
            body += f" Instead: {manual}."
    elif kind.kind == "image":
        body = ("It is an image: this model cannot see images. If it shows text, extract it "
                f"with OCR (`tesseract {path.name} {path.stem}`).")
    elif kind.kind in ("audio", "video"):
        body = "It is a recording: it must be transcribed to text first."
    elif kind.kind == "unknown":
        body = "It is binary data, not text, and its format was not recognised."
    elif manual:
        body = f"There is no reader for this format here: {manual}."
    else:
        body = "There is no reader for this format: export it to a text format (PDF, CSV, TXT)."
    return (f"{head} {body} Tell the user what the file is and how to read it; "
            "do not guess its content.")
