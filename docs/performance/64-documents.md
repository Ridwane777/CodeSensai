# Issue #64 — Reading and indexing documents: real trials

Decision: [ADR-0034](../decisions/0034-read-all-file-formats.md).

**Method** (2026-10-18). Client on an Intel i7-1355U laptop, Docker
29.9.1, `sensai-docs` image (MarkItDown 0.1.8, 659 MB) built locally.
Embeddings and chat model on the RunPod pod (Ollama 0.40.6, `bge-m3`,
`qwen3-coder:30b`).

Trial files, in a temporary folder outside the repository:
- `requirements.pdf`: a real 3.3 MB project specification (the Dashboard project);
- `cahier.docx`, `budget.xlsx`, `pitch.pptx`: generated with the image's
  libraries;
- `plan.dwg`: an AutoCAD header.

## 1. Conversion by `read_file`

| File | Result | Time |
| --- | --- | --- |
| `requirements.pdf` | 217 lines of Markdown | 8.2 s |
| `cahier.docx` | "Requirement 1: at least two user stories per feature." | 3.0 s |
| `budget.xlsx` | Markdown table (Item, Monthly cost) | 3.1 s |
| `pitch.pptx` | Slide title and text | 4.0 s |
| `plan.dwg` | "Generic AutoCAD drawing (306 bytes)", no reader, steps to follow | 0.00 s |
| Next page of `requirements.pdf` | Reused, no new conversion | 0.000 s |

The time includes starting the container and loading MarkItDown.

## 2. The agent on the pod

With `sensai --no-rag`, so without help from RAG:
- **"According to requirements.pdf, which languages and frameworks are mandatory?"**
  The agent calls `read_file` (218 lines) and answers: none is mandatory
  ("free to use the languages and frameworks of your choice"), then gives
  the recommendations, port 8080, `/about.json` and docker-compose. Every
  claim was found in the converted text.
- **"What does plan.dwg contain?"** The agent receives the type and the steps
  to follow; it explains how to open or convert the file, without inventing
  content.

## 3. Indexing by RAG

The same folder, indexed with the real conversion and `bge-m3`, queried with
hybrid RAG and the R2 reranking. **No question names the file.**

| Question | First passage | Correct? |
| --- | --- | --- |
| Which languages and frameworks are mandatory for the project? | `requirements.pdf`, lines 91-130 | ✅ contains "free to use the languages and frameworks" and the recommended list |
| Which port must the server run on? | `requirements.pdf`, line 121 | ✅ "MUST run on port 8080" |
| How much does the GPU cost per month? | `budget.xlsx` | ✅ the table (RunPod GPU: 17) |
| How many user stories are needed per feature? | `cahier.docx` | ✅ "at least two user stories per feature" |

- First indexing: 4 documents, 11 passages, **29.5 s** (`plan.dwg` is not
  indexed).
- Next indexing with no change: **0.01 s**, no document reconverted.

## 4. Defects found by these trials, fixed

- A binary file containing null bytes decodes as UTF-8: before this change,
  `read_file` returned it as text. It is now treated as binary (Git's
  criterion: a null byte in the first 8 KB).
- `puremagic` gives DWG the type `image/x-dwg`: the agent received absurd
  OCR advice. Only raster images are classified as "image".
- On a damaged PDF, MarkItDown returns the raw file as text: RAG would have
  indexed it. This case is rejected in the image (exit code 3) and on the
  agent side.
- The CLI tests launched the real Docker: they now use a fake converter.

## 5. Limits

- **Time:** 3 to 8 s per conversion. A project with many documents makes the
  first indexing longer.
- **Quality of some PDFs:** in this specification, words are stuck together
  ("highlycustomizabledashboard"), a known pdfminer defect. The model still
  understood, and search found the right passages.
- **Cited line numbers** for a document are those of the converted Markdown,
  not the PDF pages.
- **No OCR**, no image description, no audio transcription.
- **A small sample:** 4 questions on 4 files. This is a functional check, not
  a quality measurement like those of R1 and R2.
