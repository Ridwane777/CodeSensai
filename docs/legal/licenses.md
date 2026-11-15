# Licences

*Version of 2026-10-14. Non-commercial project; this text does not replace
advice from a lawyer.* The full list of dependencies, with their role and
fallback, is in [dependencies.md](../dependencies.md).

## What we use

| Component | Licence | What it requires from us | Checked |
| --- | --- | --- | --- |
| Ollama | MIT | Keep the copyright notice if we redistribute Ollama (we do not: everyone installs it) | Official GitHub page |
| Qwen3-8B (`qwen3:8b`) | Apache-2.0 | Keep the licence and notice if we redistribute the weights; state changes. Commercial use allowed. | Official Hugging Face card |
| Qwen3-Coder-30B-A3B-Instruct (`qwen3-coder:30b`) | Apache-2.0 | Same | Official Hugging Face card |
| `nemotron-3-nano:30b` (candidate) | **Not checked** | Read it **before** using it: NVIDIA models often have their own licence | - |
| `requests` | Apache-2.0 | Same as Apache | Package metadata |
| `docker` (Python SDK) | Apache-2.0 | Same as Apache | Package metadata |
| `puremagic` | MIT | Keep the notice | Package metadata |
| `fastapi`, `pydantic`, `pydantic_core`, `anyio`, `h11`, `annotated-types`, `annotated-doc`, `typing-inspection` | MIT | Keep the notice | Package metadata |
| `uvicorn`, `starlette`, `click`, `httpcore`, `httpx` (tests) | BSD-3-Clause | Keep the notice | Package metadata |
| `opentelemetry-api` (FastAPI dependency) | Apache-2.0 | Keep the notice and the change statements | Package metadata |
| `typing_extensions` | PSF-2.0 | Keep the notice | Package metadata |
| MarkItDown, in the `sensai-docs` image (not installed in CodeSensai) | MIT | Keep the notice if the image is distributed | microsoft/markitdown repository |
| `rich`, `markdown-it-py`, `mdurl`, `wcwidth` | MIT | Keep the notice | Package metadata |
| `prompt_toolkit` | BSD-3-Clause | Keep the notice; do not use the authors' names to promote the project | Package metadata |
| `Pygments` (`rich` dependency) | BSD-2-Clause | Keep the notice | Package metadata |
| `numpy` | BSD-3-Clause (and 0BSD, MIT, Zlib, CC0-1.0 for bundled parts) | Keep the notice | Package metadata |
| `bge-m3` (RAG embeddings) | MIT | Keep the notice if we redistribute the weights | Official Hugging Face card |
| Chromium (`sensai-browser` image, built locally) | BSD-3-Clause and the licences of its components | Nothing as long as we do not redistribute the image (everyone builds it) | Debian `chromium` package |
| `urllib3`, `charset-normalizer` | MIT | Keep the notice | Package metadata |
| `idna` | BSD-3-Clause | Keep the notice; do not use the authors' names to promote the project | Package metadata |
| `certifi` | MPL-2.0 | Copyleft **at file level**: only changes to its own files would have to be published. We do not change them. | Package metadata |
| AI portrait (`frontend/public/ai/portrait.webp`, derived from the PNG provided by Christopher) | **Not checked** | To establish **before any public release**: where this image was produced, which terms of use apply, whether reuse is allowed. It carried the text "TURNOVER MARKETING", a third party's brand: `frontend/scripts/prepare_ai_frames.py` erases it by default. Do not present the image as original until this is settled. | File provided; origin undocumented |
| `framer-motion` | MIT | Keep the notice | Package metadata |
| `pytest`, `ruff` and the `pytest` dependencies (`iniconfig`, `pluggy`: MIT; `packaging`: Apache-2.0 or BSD-2-Clause; `Pygments`: BSD-2-Clause) | - | Nothing: they are dev tools, not shipped with the product | Package metadata |

No current dependency is under a "strong copyleft" licence (GPL, AGPL), which
would require publishing CodeSensai's code under the same licence. **Check
this for every new dependency** (MCP, web framework…) in the PR that adds it.
The search engines (DuckDuckGo, Bing as fallback) are services, not
libraries: their terms are covered by risk L8 of the [analysis](README.md).

**Model answers**: the Apache-2.0 licence covers the model weights, not what
it generates. Code produced with CodeSensai belongs to the user, but it may
resemble existing licensed code: one more reason to review it.

## CodeSensai's own licence: decision to make

The repository has **no `LICENSE` file**. By default, the code is therefore
"all rights reserved" for its authors: nobody, not even a team member after
the project, formally has the right to reuse or publish it.

| Option | For | Against |
| --- | --- | --- |
| No licence (current situation) | Nothing to do | Legally unclear reuse, including for the authors; prevents publishing the project cleanly in a portfolio |
| MIT | Simple, compatible with all our dependencies, the most widespread | Anyone can reuse the code, including commercially, without giving anything back |
| Apache-2.0 | Same freedom as MIT, plus an explicit patent clause; same licence as `requests` and the Qwen models | Slightly heavier (NOTICE file, change statements) |
| AGPL-3.0 | Forces anyone offering CodeSensai as an online service to publish their changes | Hinders any commercial reuse, which contradicts a possible business model (see `docs/business/`) |

Also check, before choosing, any agreement covering ownership of the code
produced by the team. The decision will be recorded in an ADR.
