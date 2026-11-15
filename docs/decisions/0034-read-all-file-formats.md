# ADR-0034 - Read and index any file format: content-based identification, MarkItDown conversion in the sandbox, an honest answer otherwise

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-18
- **Deciders**: Ridwane (Workstream C); to be approved with Meric (Workstream B), whose `read_file` tool and sandbox are affected
- **Workstream**: C (issue #64); B (`tools/read_file_tool.py`, sandbox)

## Context
Issue #64, derived from US-R1-4: when the agent is asked about a file
that is not text (the requirements as a PDF, a specification in `.docx`, a
`.xlsx` spreadsheet), it must read the content or say precisely what to do,
never make it up. Today, `read_file` only returns "Not a UTF-8
text file (binary?)", and RAG indexing lists the skipped PDFs and office
documents with a hint (`UNSUPPORTED_FORMATS`). `pypdf` is
used nowhere.

The long-term goal: read the content, whatever the format.

What is done elsewhere:
- coding agents convert the document to text or Markdown before
  reading it. Some command-line agents read PDFs natively, and conversion "skills"
  can be added (pdfplumber, MinerU); OpenHands integrates
  PDF conversion;
- MarkItDown (Microsoft, MIT) converts to Markdown, for LLMs: PDF,
  docx, pptx, xlsx, xls, EPUB, HTML, ipynb, msg, ZIP, images (metadata)
  and audio, with optional dependencies and plugins.

Constraints:
- **Security.** pypdf had several vulnerabilities in 2025-2026: a crafted PDF
  can cause an infinite loop or consume 1 GB of memory
  (CVE-2026-59936, CVE-2026-57204, CVE-2025-66019). The recommended practice
  (Dangerzone) is to parse documents in an isolated container, with no
  network.
- **Our sandbox** (ADR-0012, `python:3.12-slim`) has neither network nor access to
  project files.
- **The number of tools.** With M4, adding a tool dropped structured
  `read_file` calls to 1/5 (#78): every extra tool disturbs
  qwen3-coder.

## Considered options

**Where to plug in reading**

| Option | Pros | Cons |
| --- | --- | --- |
| A new `explain_format` tool (what the issue says) | No change to `read_file` | The model must think to call it; one more tool, which made M4 regress |
| **Inside `read_file`** (chosen) | The model does what it already does; no extra tool | Modifies a Workstream B file |

**What to convert with**

| Option | Pros | Cons |
| --- | --- | --- |
| pypdf alone (BSD-3) | Light, pure Python | PDF only; weaker on column layouts; recent vulnerabilities |
| pdfplumber (MIT) | Good tables | PDF only |
| PyMuPDF / PyMuPDF4LLM | Very fast, structured Markdown | **AGPL-3.0**: commercial license needed for a closed product (business plan) |
| Docling (IBM), Marker, MinerU | Layout, OCR | Heavy (models, torch); oversized |
| **MarkItDown (MIT), extras `pdf`, `docx`, `pptx`, `xlsx`, `xls`, `outlook`** (chosen) | One tool for most common formats; designed for LLMs; plugins | More dependencies (pdfminer.six, pdfplumber, mammoth, lxml, openpyxl…); average quality on complex PDFs |

**When to convert: on demand only, or also at RAG indexing**

| Option | Pros | Cons |
| --- | --- | --- |
| Only when the agent calls `read_file` | No indexing cost | A question that does not name the file ("which frameworks are mandated?") never finds the requirements PDF |
| **Also at RAG indexing** (chosen) | This is what document RAGs do: LlamaIndex (`SimpleDirectoryReader`), AnythingLLM and PrivateGPT index PDF, docx, xlsx, pptx by default; it is what US-R1-4 asks for | 3 to 8 s per document on first indexing; Docker required to benefit |

Code indexers stick to code, but CodeSensai must
also answer about the project's documents (US-R1-4).

**Where to run the conversion**

| Option | Pros | Cons |
| --- | --- | --- |
| In the agent process | Simple, fast | A crafted file can hang or saturate the agent |
| **In the sandbox, `sensai-docs` image** (chosen) | A crafted file only reaches a disposable container, with no network, and limited memory, CPU and time | Docker mandatory; a 659 MB image to build; 3 to 8 s per conversion (measured) |

## Decision
`read_file` handles any file in four levels:

1. **Identify the type by content** (magic bytes, `puremagic`,
   pure Python, MIT), not by extension.
2. **Text** (code, Markdown, CSV, JSON, XML…): read directly, as
   today.
3. **Known document format**: converted to Markdown by MarkItDown, in a
   `sensai-docs` container. The file is copied there read-only, the
   container has no network, and sandbox limits apply.
4. **Everything else**, or an empty conversion: a response that names the detected
   type, gives the size and the steps to follow (`ocrmypdf` for a
   scanned PDF, an export for a proprietary format, the command to
   build the image if it is missing). Never invented content.

No new tool is offered to the model.

**At RAG indexing**, PDF, docx, pptx, xlsx, xls, EPUB and msg files under
20 MB are converted by the same container, then chunked as
Markdown: its line numbers are the ones `read_file` returns for the
same file. A document is only reconverted if it has changed. If
conversion fails (Docker missing, image not built, scanned PDF), the
document is listed with the steps to follow, as before, and retried at
the next indexing.

Measured safeguard: when a parser fails, MarkItDown returns the raw
file; output that reproduces the start of the file or contains a null byte
is rejected (in the image and on the agent side).

## Consequences
- ✅ The agent reads common office formats, and for all others it knows what the file is and what to do.
- ✅ The RAG finds a document without it being named: 4 questions out of 4 find the right passage (PDF, docx, xlsx), measured on the pod (`docs/performance/64-documents.md`).
- ✅ A crafted document does not touch the agent: same principle as Dangerzone.
- ✅ No extra tool for the model; an MIT license compatible with a commercial product.
- ❌ Docker and the `sensai-docs` image are required for level 3; without them, the agent only gives level 4.
- ❌ A conversion costs 3 to 8 s, measured (container startup and MarkItDown loading; subsequent pages of the same file are reused), and the image weighs 659 MB.
- ❌ Images only yield their metadata: qwen3-coder is not multimodal, and OCR (Tesseract) is postponed. Audio is not transcribed. Scanned PDFs require `ocrmypdf`.
- ❌ Quality depends on MarkItDown: PDFs with complex layouts (columns, nested tables) come out imperfect. Measured on a project requirements PDF: words glued together ("highlycustomizabledashboard"), a known pdfminer defect.
- ❌ The first indexing of a document-heavy project takes longer: 29.5 s for 4 documents (measured). Later runs only reconvert modified documents.
- ❌ Indexed documents can be sent to the model server like code: confidential requirements or specifications are affected just the same.
- ❌ A new Python dependency, `puremagic` (MIT, no dependencies), and one more Docker image to build.
- ❌ Modifies `read_file` (Workstream B) and the sandbox tooling: to be approved with Meric.
- Follow-up: tests on sample files (PDF, docx, xlsx, unknown file, empty file); trial run with the project requirements; measurement of conversion time. Revisit if a multimodal model is adopted (images), or if PDF quality is not enough (Docling).
