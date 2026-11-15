"""
[Workstream C - Ridwane] Detect a file's format and say how to read it - issue #64.

ADR-0034, levels 1 and 4: the type comes from the content (magic bytes), not
the extension. A known document format (`CONVERTIBLE`) is converted to text
in the sandbox (`execution/sandbox/document_sandbox.py`); for everything else,
`unreadable_message` names the type and gives the steps to follow, so the
model never invents the content.

Messages are in English, like the rest of what `read_file` returns to the
model.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

import puremagic

# Formats MarkItDown converts to text (extras installed in the sensai-docs
# image: docker/docs/Dockerfile).
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

# Extension given to the file in the container: MarkItDown uses it to pick
# its converter.
EXTENSIONS = {kind: f".{kind}" for kind in CONVERTIBLE}

# Steps to follow without the converter, per type.
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

# Raster images: the ones OCR can read. puremagic also files vector or CAD
# drawings under image/ (AutoCAD: image/x-dwg).
RASTER_IMAGES = frozenset({"image/png", "image/jpeg", "image/gif", "image/bmp",
                           "image/tiff", "image/webp"})

_OLE = bytes.fromhex("d0cf11e0a1b11ae1")  # container of Office 97-2003 formats and .msg
_OLE_KINDS = {".xls": "xls", ".msg": "msg", ".doc": "doc", ".ppt": "ppt"}


@dataclass(frozen=True)
class FileKind:
    kind: str    # "pdf", "docx", …, "image", "audio", "video", "other" or "unknown"
    label: str   # readable description: "PDF", "Generic AutoCAD drawing"
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
    """The type of `path`, from its first bytes (and a ZIP archive's listing)."""
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
    """A null byte in the first 8 KB means binary, even if it decodes as UTF-8
    (Git's criterion)."""
    with open(path, "rb") as handle:
        return b"\x00" in handle.read(8192)


def unreadable_message(path: Path, kind: FileKind, reason: str | None = None) -> str:
    """What the model receives when it cannot read the content (level 4).

    `reason`: why conversion produced no text (`image_missing`, `empty`,
    `timeout`…), or None if the format is not convertible.
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
