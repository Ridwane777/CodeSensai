# CodeSensai dependencies

Everything the project depends on to run, to be developed and to be
demonstrated: libraries, software, models, providers, services. For each one,
what happens if it disappears.

Status as of 2026-10-14. The "installed" versions are those of `requirements.txt`
and `requirements-dev.txt`, checked in a clean environment (Python 3.12,
`pip check` with no conflict, 844 tests). Library licences come from their
installed metadata. Those of the models and of Ollama were checked on their
official page (sources at the bottom of the page).
To update with every dependency added: the PR that adds it completes this
file.

## Principle: as few dependencies as possible

The project requirements forbid any LLM framework (LangChain, LlamaIndex…) and requires
talking to Ollama over plain HTTP ([ADR-0001](decisions/0001-no-llm-framework.md)).
The engine has **three** declared Python dependencies for its operation: `requests`, `numpy`
for the RAG search (R1, [ADR-0009](decisions/0009-rag-over-the-codebase.md)),
and `docker` to drive the sandboxes (T2, T3, [ADR-0012](decisions/0012-docker-chromium-sandbox.md)).
The CLI adds `rich` and `prompt_toolkit` for its display: they are not LLM
frameworks, they touch neither the model nor the agent.
Everything else comes from the standard library (`json`, `sqlite3`, `ast`,
`threading`, `dataclasses`…).

## 1. Used today

### Python libraries

| Dependency | Version (declared → installed) | Role | Licence | If it disappears |
| --- | --- | --- | --- | --- |
| `requests` | `>=2.31` → 2.34.2 | HTTP calls to Ollama (`core/ollama_client.py`, and the RAG reranking in `knowledge/retrieval.py`) | Apache-2.0 | Low risk (very well maintained project). Replaceable by the standard library's `urllib.request` or by `httpx`: a single file to change. |
| `urllib3`, `idna`, `charset-normalizer` | transitive from `requests` | HTTP transport, encodings | MIT, BSD-3-Clause, MIT | Follow `requests`. |
| `certifi` | transitive from `requests` | Root certificates for HTTPS | **MPL-2.0** | Follows `requests`. MPL-2.0: "weak copyleft" licence, with no effect as long as its files are not modified. |
| `numpy` | `>=1.24` → 2.5.4 | Similarity search in the RAG index (`knowledge/rag.py`, R1) | BSD-3-Clause (and 0BSD, MIT, Zlib, CC0-1.0 for bundled parts) | Low risk (reference library). Measured in `docs/performance/R1-rag.md`: the same search in pure Python takes 192 ms instead of 1.4 ms for 2,000 passages, so it is replaceable on a small project. |
| `docker` (Python SDK) | `>=7.0` → 7.2.0 | Creates, limits and removes the sandbox containers (`execution/sandbox/docker_utils.py`) | Apache-2.0 | Official Docker project. Replaceable by calls to the `docker` command or to its HTTP API, in a single module (`docker_utils.py`). Without the Docker daemon, `run_code` and `web_search` answer "Docker is unavailable", everything else works. |
| `rich` | `>=13.0` → 15.0.0 | CLI display: welcome frame, colours, diffs, Markdown answer, animation (`src/sensai/ui.py`) | MIT | Without it, the CLI could fall back to `print`: only `ui.py` depends on it. Depends on `markdown-it-py`, `mdurl` (MIT) and `Pygments` (BSD-2-Clause). |
| `puremagic` | `>=2.0` → 2.2.0 | File type from its first bytes, for `read_file` and the RAG (`knowledge/documents.py`, [ADR-0034](decisions/0034-read-all-file-formats.md)) | MIT | Pure Python, no dependency. Replaceable by `python-magic` (libmagic) or by our own signatures: only `documents.py` depends on it. Without it, a binary file would no longer have a named type. |
| `fastapi` | `>=0.110` → 0.146.0 | `sensai-web` web server: routes, request validation, SSE streams (`web/server.py`, [ADR-0035](decisions/0035-real-web-server.md)) | MIT | Only `web/server.py` depends on it; replaceable by Starlette alone (less validation) or by Flask (synchronous, see ADR-0035). Without it, the CLI works. Depends on `starlette` (BSD-3-Clause), `pydantic` and `pydantic_core` (MIT), `annotated-types`, `annotated-doc`, `typing-inspection` (MIT), `typing_extensions` (PSF-2.0) and `opentelemetry-api` (Apache-2.0). |
| `uvicorn` | `>=0.29` → 0.54.0 | HTTP server that runs `sensai-web` (`web/cli.py`) | BSD-3-Clause | Replaceable by Hypercorn (same ASGI interface). Depends on `h11` (MIT) and `click` (BSD-3-Clause); `anyio` (MIT) comes from Starlette. |
| `prompt_toolkit` | `>=3.0` → 3.0.53 | CLI prompt: persistent history (up arrow), completion of `/` commands (`src/sensai/ui.py`) | BSD-3-Clause | Only in an interactive terminal; otherwise the CLI uses `input()`. Replaceable by the standard library's `readline` (fewer features). Depends on `wcwidth` (MIT). |
| `pytest` | `>=8.0` → 9.1.1 (dev) | Tests | MIT | Dev tool only, not shipped. |
| `ruff` | `>=0.6` → 0.17.0 (dev) | Lint in CI | MIT | Same. The rules are pinned in `pyproject.toml` so that a new version does not break the CI on its own. |

Dependencies of `pytest` (dev): `iniconfig` (MIT), `packaging` (Apache-2.0 or
BSD-2-Clause), `pluggy` (MIT), `Pygments` (BSD-2-Clause).

`requirements.txt` pins these versions for a reproducible environment;
`pyproject.toml` keeps wide bounds so as not to block an installation.

Python: **3.12 minimum** (`pyproject.toml`), because `puremagic>=2.0`
requires it (raised from 3.10 on 2026-11-01: the CI on 3.10 could no longer
install the project). The CI and the development machines run on 3.12.

### Engine and models

| Dependency | Version / identifier | Role | Licence | If it disappears |
| --- | --- | --- | --- | --- |
| **Ollama** | 0.20.x on the workstations, 0.40.x on the RunPod pod | Server that runs the model and exposes the `/api/chat` API | MIT | **Critical** dependency: the whole agent goes through its API, including native tool calling ([ADR-0003](decisions/0003-native-ollama-tool-calling.md)). Since the API is local and open source, the installed version remains usable even if the project stopped. Plan B: a compatible server (vLLM, llama.cpp server) would require rewriting `core/ollama_client.py`, the only file that talks to Ollama. |
| **`qwen3:8b`** (Qwen3-8B) | default model in `config.json` | Day-to-day development ([ADR-0004](decisions/0004-model-and-infrastructure.md)) | Apache-2.0 | Downloaded model, so usable offline once fetched. **Warning: it is not installed on Lot A's workstation** (`ollama pull qwen3:8b` to run), and the CLI fails with "model not found" as long as it is missing. |
| **`qwen3-coder:30b`** (Qwen3-Coder-30B-A3B-Instruct) | validation and demo model | Demo on the RunPod pod (ADR-0004); also reranks the RAG passages (R2, [ADR-0032](decisions/0032-hybrid-rag-and-reranking.md): the measurements only hold for it) | Apache-2.0 | Same: downloadable weights. Fallback: `qwen3:8b`, of lower quality for tool calls. |
| **`bge-m3`** (BAAI) | default embedding model (`--rag-model`) | Computes the RAG embeddings via `/api/embed` (R1, [ADR-0009](decisions/0009-rag-over-the-codebase.md)); chosen by measurement against `nomic-embed-text` and `qwen3-embedding` | MIT | 1.2 GB to download (`ollama pull bge-m3`). Without it, the CLI warns and continues without search (`--no-rag`). Measured fallback: `qwen3-embedding:0.6b` (10/15 instead of 11/15), with a threshold to recalibrate. |
| **Judge model** (EV1, [ADR-0019](decisions/0019-llm-judge-evaluation.md)) | by default the model in `config.json` (`qwen3:8b`); `--judge-model` for another one | `sensai-eval`: scores and per-claim verdicts, via `POST /api/chat` in JSON mode (`eval/judge.py`) | that of the chosen model (Apache-2.0 for `qwen3:8b`) | No Python library added. Without Ollama, `sensai-eval run` writes a report where every case is `judge_error`. **Bias:** judge = same model as the agent by default (self-preference); a second model requires one more download. The judge prompt is in the repository (`prompts/judge/`), not at a third party. |
| `nemotron-3-nano:30b` | candidate to compare (ADR-0004) | Second choice for an A/B test | **not checked** | To check before using it: NVIDIA models often have their own licence, more restrictive than Apache-2.0. |

### Isolated execution

| Dependency | Version / identifier | Role | Licence | If it disappears |
| --- | --- | --- | --- | --- |
| **Docker Engine** | local daemon | Runs the sandboxes ([ADR-0012](decisions/0012-docker-chromium-sandbox.md)) | Apache-2.0 | **Every demo machine must have Docker.** Without it, the agent works without code execution or web search. |
| **`python:3.12-slim`** image | pulled from Docker Hub | `run_code` container | Python: PSF; Debian: free licences of its packages | Very widespread official image; another minimal Python image works (the sandbox's `config.py`). |
| **`sensai-docs`** image | built locally (`docker/docs/Dockerfile`, `python:3.12-slim` + `markitdown[pdf,docx,pptx,xlsx,xls,outlook]==0.1.8`) | Converts documents to Markdown for `read_file` and the RAG ([ADR-0034](decisions/0034-read-all-file-formats.md)) | MarkItDown: MIT; its parsers (pdfminer.six, pdfplumber, mammoth, openpyxl, python-pptx…): permissive free licences | 659 MB. Without it, documents are listed with the steps to follow and `read_file` explains how to convert them. MarkItDown is not an LLM framework (ADR-0001): it only converts files. Replaceable by Docling (heavier) or by pdfplumber alone (PDF only). |
| **`sensai-browser`** image | built locally (`docker/browser/Dockerfile`, Debian bookworm + Chromium) | `web_search` container | Chromium: BSD-3-Clause and the licences of its components | Nothing to download from a private registry; 1.1 GB, about 12 min to build. |

### Web interface (`frontend/` folder, Node 22 minimum, required by `jsdom` 30 (`^22.22.2 || ^24.15.0 || >=26`) and `jest-dom` 7 (`>=22`))

Dependencies of the frontend only; they do not touch the Python engine.
Versions and licences taken from the installed `package.json` files (2026-10-13).

| Dependency | Installed version | Role | Licence | If it disappears |
| --- | --- | --- | --- | --- |
| `react`, `react-dom` | 18.3.1 | Interface rendering | MIT | Very low risk (very well maintained); replacing React would mean rewriting every component. |
| `react-router-dom` | 6.30.6 | Navigation between pages (`HashRouter` mode, suited to static hosting) | MIT | Low: about ten routes, replaceable by a small home-made router. |
| `vite`, `@vitejs/plugin-react` | 5.4.21, 4.7.0 | Development server and build | MIT | Build tool: replaceable (webpack, esbuild) without touching the code. |
| `typescript` | 5.9.3 | Typing of the event contract and of the components | Apache-2.0 | Dev tool; the compiled JS remains usable. |
| `tailwindcss`, `postcss`, `autoprefixer` | 3.4.19, 8.5.30, 10.6.1 | Styles (colour tokens in `src/index.css`) | MIT | The generated CSS stays valid; classes to rewrite if the tool disappeared. |
| `@fontsource-variable/plus-jakarta-sans` | 5.3.0 | Embedded font (no CDN call) | **OFL-1.1** | Replaceable by a system font: one line of CSS. OFL-1.1 allows use and redistribution with the font; do not sell it on its own. |
| `framer-motion` | 11.18.2 | Interface animations (appearances, counters, mouse parallax, stop-motion entrances, [ADR-0026](decisions/0026-animated-code-universe.md)); respects `prefers-reduced-motion` | MIT | Low: components stay displayed without animation; replaceable by CSS transitions. |
| `vitest`, `jsdom`, `@testing-library/*` | 2.1.9, 30.1.2, react 16.3.3, dom 10.4.2, jest-dom 7.0.1, user-event 14.6.8 | Tests (dev only) | MIT | Dev tools, not shipped. |

The AI portrait (`frontend/public/ai/portrait.webp`) is provided by the team; its origin and rights are still to be checked ([licences](legal/licenses.md)). The script that prepares it requires `pillow`, `numpy` and `scipy` (outside the engine requirements, to install only to replay it). No AI library or LLM client on the frontend side ([ADR-0001](decisions/0001-no-llm-framework.md)).

### Providers and services

| Dependency | Role | Secrets / quotas | If it disappears |
| --- | --- | --- | --- |
| **RunPod** | Rental of a 24 GB GPU (RTX 3090/4090) to run `qwen3-coder:30b` ([ADR-0004](decisions/0004-model-and-infrastructure.md)) | Credit **bought** by the team (amount to fill in `business/costs.md`). Account and pod address: **never in the repository** (CONTRIBUTING). | **Critical dependency for the demo**, not for development. Plans B: Azure free credits ($100 credit, T4 GPU under quota, see [infra-options.md](research/infra-options.md)), or `qwen3:8b` locally. Prepare recordings of the demo. |
| **GitHub** (repository `Ridwane777/…`) | Code, PRs, reviews (CODEOWNERS) | Write access for the 4 members | The Git repository is complete on every workstation: nothing is lost, only the review circuit stops. |
| **GitHub Actions** | CI: `ruff` + `pytest` on every PR (`actions/checkout@v4`, `actions/setup-python@v5`) | Organisation's free minutes | Run `pytest -q && ruff check src tests` by hand before every merge. |
| **DuckDuckGo** (`html.duckduckgo.com`, HTML page, no key) | `web_search` engine tried first ([ADR-0040](decisions/0040-duckduckgo-web-search-with-bing-fallback.md)) | No secret, no known quota. Automated access not guaranteed by its terms; has already served an anti-bot challenge to another network (2026-10-14). | The tool switches to Bing (fallback), then returns the error of the last engine tried. |
| **Bing** (`www.bing.com`, HTML page, no key), fallback engine since ADR-0040 | `web_search` engine ([ADR-0014](decisions/0014-bing-search-engine.md)), with an ordinary Chrome *user-agent* ([ADR-0017](decisions/0017-search-browser-user-agent.md)) | No secret, no known quota. **Microsoft's terms restrict automated access**, and the HTML markup is not guaranteed. Queries go to Microsoft (see the privacy policy). | The tool returns `SearchBlocked`, `SearchEmptyPage` or `SearchUnexpectedPage`, the rest of the agent works. Plan B: self-hosted SearXNG or a search API (section 2). |
| **ClickUp** | Team planning and tasks | Members' accounts | No impact on the product. Important decisions are also in the ADRs, not only in ClickUp. |

## 2. Planned, not yet in `main`

To complete (version, licence, plan B) in the PR that adds them, with an ADR
when it is a structural choice.

| Dependency | For which feature | Status |
| --- | --- | --- |
| MCP library (client and server) | [T1] MCP | **None**: stdio client written by hand ([ADR-0041](decisions/0041-in-house-mcp-client.md)). The MCP servers declared in `config.json` are third-party code launched on the machine: only add trusted servers. |
| Web framework | [X1] Web interface | **Chosen and used**: FastAPI + Uvicorn ([ADR-0035](decisions/0035-real-web-server.md)), in `requirements.txt`; see section 1. |
| Embedding model + vector storage | [R2] Advanced RAG, [A6] Semantic cache | For R1: `bge-m3` served by Ollama, SQLite + `numpy` storage (section 1). R2 and A6 will reuse these embeddings. |
| Web search API (Brave Search, SearXNG…) | [T3] Web search, if Bing blocks | Plan B, not chosen: `web_search` currently reads Bing's page without an API (section 1). **Point of attention**: API key (secret), quotas, and the provider's terms of use (some forbid storing the results). |

## 3. Secrets

| Secret | Used today? | Where to put it |
| --- | --- | --- |
| IP address / URL of the RunPod pod | Yes (demo) | As the `--host` argument, never in the repository's `config.json`. `config.local.json` is ignored by Git but **is not read by the code**: do not rely on it |
| Web search API key | No (Bing is read without a key) | Environment variable or `.env` (ignored by Git) |
| Web interface access credentials | Yes: `sensai-web` prints a random access token at start-up (`secrets.token_urlsafe(32)` in `src/sensai/web/cli.py`), required by the API as a bearer token ([ADR-0023](decisions/0023-web-api-access.md)) | Nowhere: the token changes at every start and is never written to disk; paste it into the interface |

The repository currently contains **no** secret: checked by reading
`config.json` and `.gitignore` (which excludes `.env` and `config.local.json`).

## Sources

- Qwen3-8B licence: <https://huggingface.co/Qwen/Qwen3-8B> (apache-2.0)
- Qwen3-Coder-30B-A3B-Instruct licence: <https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct> (apache-2.0)
- bge-m3 licence: <https://huggingface.co/BAAI/bge-m3> (mit)
- numpy licence: installed package metadata (`License-Expression`)
- Ollama licence: <https://github.com/ollama/ollama/blob/main/LICENSE> (MIT)
- Frontend dependency licences: `license` field of the `package.json` files in `frontend/node_modules/`
- RunPod security and compliance: <https://docs.runpod.io/references/security-and-compliance>
