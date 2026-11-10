# ADR-0009 — RAG over the project: bge-m3, SQLite + numpy, automatic indexing

- **Status**: Accepted (2026-11-01, approved by the team); threshold (decision 8) and ranking superseded by [ADR-0032](0032-hybrid-rag-and-reranking.md)
- **Date**: 2026-10-11
- **Deciders**: Ridwane NICO (Workstream C), to be approved by the team
- **Workstream**: C (impacts A: `RagTool` waits for the ReAct loop)

## Context
Feature [R1] Basic RAG must let you ask a question about the project's code
and documentation and get an answer that cites the right passage (ClickUp
Definition of Done). The catalog describes the pipeline: ingest, chunk,
compute embeddings, store in a local vector database, retrieve by
similarity, inject into the context. Detailed needs:
[R1 user stories](../user-stories/R1-basic-rag.md).

Constraints:
- **No LLM framework** ([ADR-0001](0001-no-llm-framework.md)): no
  LlamaIndex or LangChain; embeddings go through the Ollama HTTP API
  (`/api/embed`).
- **Questions in French, about code**: the embedding model must handle
  both.
- **Team machines without a GPU**, disks sometimes nearly full: every
  dependency and every GB counts.
- **The ReAct loop (Workstream A) is not delivered**: whatever depends on it
  must not block R1.
- **Any indexed passage may be sent to the model**, including on the remote
  pod (ADR-0004): indexing must never touch secrets.

Decisions 1, 2 and 8 rely on measurements:
[docs/performance/R1-rag.md](../performance/R1-rag.md).

## Considered options

**1. Vector database and search**

| Option | Pros | Cons |
| --- | --- | --- |
| **SQLite + exhaustive search with numpy** (chosen) | Same database as M1 (ADR-0007). Measured: 1.4 ms for 2,000 passages, 18 ms for 100,000. No SQLite extension to load | One dependency (numpy), very common |
| SQLite + pure-Python search | No dependency | Measured at 192 ms for 2,000 passages, 1.6 s for 20,000, 8.3 s for 100,000: the wait is visible on every question |
| sqlite-vec | Fast | C extension to load into SQLite, disabled on some Python installs (including macOS): "works on my machine" risk, for a gain useless at our scale |
| FAISS | Very fast on millions of vectors, approximate indexes | Heavy compiled dependency; approximate indexes can miss the best passage |
| ChromaDB | Full vector database | Several hundred MB of dependencies |

**2. Embedding model** (measured on 15 French questions about this repository)

| Option | Pros | Cons |
| --- | --- | --- |
| **`bge-m3`** (chosen) | Right file in 1st position 11/15, MRR 0.842; the only model that clearly separates unanswerable questions (margin 0.057) | 1.2 GB; indexing 2.2 times slower than nomic (311 s vs 141 s on 8 vCPU) |
| `nomic-embed-text` | Lightest (274 MB) and fastest | 8/15 in 1st position; an unanswerable question ("Kafka") scores higher than some real questions: no threshold possible, US-R1-3 infeasible |
| `qwen3-embedding:0.6b` | 10/15 in 1st position | Indexing 4.4 times slower than nomic (615 s); very small threshold margin (0.025) |

**3. File chunking**

| Option | Pros | Cons |
| --- | --- | --- |
| **Structure-based** (chosen): one Python function or class per passage (`ast`), one section per heading in Markdown, overlapping line blocks elsewhere | Each passage keeps its file and lines, to cite `file:lines`. The measurement shows the problem with fixed blocks: an answer found only in `cli.py` is drowned in a 40-line block and missed by all three models | More code (one chunker per format) |
| Fixed-size blocks everywhere | Simpler | Cuts functions and mixes topics in the same passage |

**4. How passages reach the model**

| Option | Pros | Cons |
| --- | --- | --- |
| **Both** (chosen): automatic injection of the best passages on every question, and `RagTool` (`search_codebase`) for the ReAct loop | Works with the current CLI, and ready for Workstream A | Two paths to maintain |
| Tool only | More "agentic" | Nothing works before Workstream A delivers |
| Injection only | Works right away | The model cannot search a second time on its own |

**5. When to index**

| Option | Pros | Cons |
| --- | --- | --- |
| **Automatically, on the first question, then only modified files** (chosen) | Nothing to run by hand: the Claude Code experience (which itself searches on demand with `grep`, without embeddings: we borrow the experience, not the mechanism). A progress display is shown | A slow first question on a new project |
| Explicit command (`/index`) | No surprise delay | A step the user has to know about |
| Full indexing at every launch | Always up to date | Several minutes of waiting at every startup |

**6. What is never indexed**

| Option | Pros | Cons |
| --- | --- | --- |
| **The project's `.gitignore`, plus a hard-coded deny list** (chosen): `.git`, `.venv`, `node_modules`, `__pycache__`, binaries, files that are too large, and `.env*`, `*.pem`, `*.key`, `id_rsa*`, secret files | Secrets stay excluded even if `.gitignore` forgets them | A list to keep up to date |
| `.gitignore` only | Nothing to maintain | A project without `.gitignore`, or with an incomplete one, would send its secrets to the model |

**7. Supported formats**

| Option | Pros | Cons |
| --- | --- | --- |
| **Text and Markdown (code included); for other formats, a hint (what to install or convert)** (chosen) | No dependency. Until the ReAct loop lands, indexing itself displays skipped files and the hint | PDFs are not read (US-R1-4 limited) |
| PDF via `pypdf` | Directly covers project specifications (US-R1-4) | A dependency, and often imperfect extraction (layout, columns) |

**8. "Nothing found" threshold**

| Option | Pros | Cons |
| --- | --- | --- |
| **Similarity threshold tuned by measurement, configurable** (chosen): 0.50 for bge-m3, in the middle of the measured interval (weakest real question 0.524, strongest unanswerable question 0.467), confirmed with the shipped chunking (0.524 vs 0.494: margin of 0.03) | Below the threshold, nothing is injected and the model is told (US-R1-3); value defensible by measurement | Small margin, to re-measure if the repository or the model changes |
| Hand-picked threshold | Simple | Arbitrary, impossible to defend |
| No threshold | Always some passages | Off-topic passages are injected, and the model cites them as if they answered |

## Decision
- Index in SQLite, in M1's data folder (`~/.sensai/`, permissions `700`),
  tied to the project like sessions; exhaustive search with numpy.
- `bge-m3` embeddings via Ollama's `/api/embed`; configurable model.
- Structure-based chunking (Python via `ast`, Markdown by headings, line
  blocks elsewhere), with file and lines for each passage.
- Automatic injection of the best passages on every question + `RagTool`
  for the ReAct loop.
- Automatic indexing on the first question, then only of added, modified or
  deleted files.
- Exclusions: `.gitignore` + hard-coded deny list, which takes precedence.
- Text and Markdown only; other formats are listed with a hint.
- Configurable similarity threshold (`rag_min_score`), 0.50, confirmed by the
  recalibration of 2026-10-11.

## Consequences
- ✅ Works without the ReAct loop: R1's DoD is reachable with the current
  CLI.
- ✅ Choice of model, search and threshold based on reproducible
  measurements.
- ✅ Secrets cannot be indexed, even with an incomplete `.gitignore`.
- ✅ A single storage technology for M1 and R1.
- ❌ **New dependency: numpy.** Common and BSD-licensed, but the project's
  first dependency besides `requests`.
- ❌ **1.2 GB model to download** (bge-m3), and a slow first question on a
  new project (311 s for this small repository on 8 vCPU, more on a laptop
  without a GPU).
- ❌ The 0.50 threshold rests on 3 unanswerable questions, and its margin is
  only 0.03 with the shipped chunking: to re-measure as the repository grows
  or if the embedding model changes.
- ❌ Real trial run on CPU: with 5 passages, the question sent is long
  enough for qwen3:8b to exceed the Ollama client's 60 s timeout; with 2
  passages, the answer cites the right passage. On GPU (RunPod pod,
  qwen3-coder:30b), the 5 passages go through and the DoD is met, except on
  the first call, when model loading exceeds that same timeout: preload
  before a demo. See docs/performance/R1-rag.md.
- ✅ Each line of a passage is sent with its number: without it, the model
  guessed which lines to cite (added after the real trial run).
- ❌ PDF and other formats not indexed: US-R1-4 only works on text and
  Markdown.
- ❌ What depends on the ReAct loop (calling `RagTool`, "unsupported format"
  tool) waits for Workstream A: ClickUp subtasks in "update required".
- ❌ Beyond a few hundred thousand passages, exhaustive search will no
  longer suffice: then switch to an approximate index (FAISS, sqlite-vec).
