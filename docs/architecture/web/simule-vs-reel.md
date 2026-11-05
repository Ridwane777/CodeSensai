# What is simulated and what is real

Transparency page for the demos. It answers one question: **in the web
interface, what really runs the agent, and what is played from a script?**

## State on 2026-10-29

Checked in `main` after PRs #99 to #105 (merged on 2026-10-29), then on branch
`lot-d/web-real-features` (same day, not merged yet: rows marked "Update on
2026-10-29, branch"), in
`src/sensai/web/server.py`, `src/sensai/web/runtime.py`,
`frontend/src/engine/wire.ts`, `frontend/src/engine/httpEngine.ts` and
`frontend/src/pages/*.tsx`.

**What was added on 2026-10-29 was tried with the real model**
(`qwen3-coder:30b`) **on 2026-11-01** ([trial](../../performance/essais/essai-2026-11-01.md),
open findings 2 to 6 listed there; finding 1 fixed in PR #108). Before that, the evidence was automated tests (pytest with a scripted
model, vitest) and, for reopening a conversation and the chat display, a
headless Chromium run against a local `sensai-web` started without a model.
"Real" below means "the interface calls the real server and agent code", not
"seen working with the model".

Without a server, the whole interface falls back to the simulated engine and
the "Moteur simulé" badge says so.

| Feature (web) | State | Evidence |
| --- | --- | --- |
| Chat, streamed answer (B1, X1) | Real | `POST /api/sessions/{id}/messages` (SSE) in `server.py`; `token` in `wire.ts` ([ADR-0035](../../decisions/0035-serveur-web-reel.md)) |
| Reasoning and tool calls (A1) | Real | `thought`, `tool_call`, `tool_return` in `wire.ts` |
| Confirmation before writing or running (A3) | Real | `POST /confirm`; `confirm_request` in `wire.ts`; `write_file` card shows the server's diff in colour (#103) |
| Stop, redirect, branches (X2) | Real | `POST /interrupt`, `POST /fork`; Escape also stops the answer (#103) |
| "↻ Régénérer" | Real | Sends `/again` to the server (skips the A6 cache) in `useEngine.tsx`; with the simulated engine the same question is replayed |
| Markdown answers, file attachments | Real (browser only) | Hand-written renderer, no raw HTML ([ADR-0049](../../decisions/0049-hand-written-markdown-rendering.md)); text files read in the browser, max 3, 20,000 chars per message; no PDF/docx |
| Questions by form (X4) | Real | `ask_user` tool, `question` event, `POST /api/sessions/{id}/answer` ([ADR-0046](../../decisions/0046-ask-user-tool.md), Proposed) |
| Agent relays and sub-agent steps (A2) | Real | Update on 2026-10-29, branch: `agent_handoff` events ([ADR-0047](../../decisions/0047-real-agent-handoffs-in-the-web.md)) plus one `subagent_step` per tool a sub-agent runs (`delegate_task` and every `team_task` role), shown as "role › tool" in the reasoning steps; `content` cut at 600 characters ([ADR-0050](../../decisions/0050-real-web-features-on-demand-evaluation.md), Proposed) |
| MCP badge (T1) | Real | Tools named `mcp_<server>_<tool>` get an "MCP" badge in the reasoning ribbon |
| RAG sources, cache hit, input guardrails (R1, A6, EV2) | Real | `rag_sources`, `cache_hit`, `guardrail` emitted by `runtime.py`, read in `wire.ts` |
| `/…` commands | Real | Handled by the server |
| Layout: left sidebar (X1) | Real (interface only) | Update on 2026-10-29, branch: `frontend/src/ui/Sidebar.tsx` holds the conversations and every tab, engine badge and theme toggle at the bottom, drawer on small screens |
| Sessions: list, reopen, delete, sidebar (M1, #44) | Real | `GET /api/sessions`, `GET /api/sessions/{id}`, `POST /api/sessions/{id}/delete`; Memory page "Rouvrir"; deleted text stayed in SQLite free pages until the next VACUUM, fixed on 2026-10-29 (`delete` now runs `VACUUM`) |
| Export JSON / Markdown / PDF (X3) | Real | Done in the browser (`frontend/src/export/`); with the server, "Conversation du serveur" buttons download `GET /export` (secrets masked) (2026-10-31) |
| Share link (X3) | Real | `POST /share`, `GET /share/<token>`, `POST /api/shares/<token>/revoke` ([ADR-0048](../../decisions/0048-share-links.md), Accepted); "Révoquer le lien" button on the Export page (2026-10-31); fake link (labelled) only with the simulated engine |
| Journal page (EV3) | Real (checked with the real model on 2026-11-01) | Update on 2026-11-01: with the server, the journal of the open conversation comes from `GET /api/journal` (stored in `<data_dir>/journal.db` by the web server and the CLI, [ADR-0053](../../decisions/0053-server-side-turn-journal.md)), and "Tous les outils" from `GET /api/journal/metrics` (per tool and model time, 7 days). Durations measured by the server. With the simulated engine the page keeps the in-browser view of the tab's events |
| Profile, facts (M1, M3) | Real | Update on 2026-10-29: the Memory page reads `GET /api/profile` and `GET /api/facts`; "Ajouter" and "Tout oublier" call `POST /api/profile/preferences` and `POST /api/profile/forget`. With the simulated engine it keeps the demo data (`useDemo`) |
| State document and Artefact panel (M4) | Real | Update on 2026-10-29, branch: `GET /api/state` returns `bodies`, which fill the Artefact panel at load; each section changed by `update_state` sends an `artifact_patch` event |
| Token usage bar and compression (M2) | Real (estimated counts) | Update on 2026-10-29, branch: `usage` event every turn (`used`, `budget`, `num_ctx`, `estimated: true`, characters / 4, [ADR-0045](../../decisions/0045-token-budget-sliding-summary.md)) and `compression` (`saved_tokens`) when the sliding summary ran |
| Few-shot examples (A7) | Real | Update on 2026-10-29, branch: same settings as the CLI (`fewshot_examples`, `fewshot_min_score`), `fewshot` event; a missing or broken file becomes a notice |
| Eval scores (EV1), Quality page | Real (2026-11-01) | Update on 2026-10-29, branch: "Évaluer la dernière réponse" calls `POST /api/sessions/{id}/evaluate` (`sensai-eval` judge, one model call, on demand only); demo rows hidden with the real server. Since 2026-11-01 the attacks table (EV4) is the real corpus, re-run from the page ("Relancer les attaques", `POST /api/quality/adversarial/run`); the T5 card was removed (T5 is a terminal command) |
| "Agent actif" persona selector (A5, Lot A) | Real (2026-11-01, checked with the real model on 2026-11-01) | Lists the personas of `config.json` (`GET /api/personas`) and sets the persona of the open conversation (`POST /api/sessions/{id}/persona`): persona block in the system prompt, its disabled tools refused for the agent and its sub-agents, cache bypassed when it disables tools. Held in server memory, not saved; a new conversation or a branch starts from the default. Persona creation and keyword routing stay CLI-only ([ADR-0054](../../decisions/0054-personas-in-the-web.md)). Simulated profiles only with the simulated engine |
| Planning page (X5) | Real (editing only) | Update on 2026-10-29, branch: lists, adds, pauses and removes the tasks of `<data_dir>/schedule/tasks.json` through `/api/schedule/tasks`; **the web server runs no task**, `sensai-schedule loop` (or `run-due`) does |
| Agents page | Real with the server (2026-10-31; personas 2026-11-01) | Shows the real agent from `GET /api/config` (model, project, RAG, cache), the real personas with their disabled tools and the one active in the open conversation ([ADR-0054](../../decisions/0054-personas-in-the-web.md)), and the session's relays; demo profiles only with the simulated engine |
| Home page (X1) | Real (2026-10-31) | The question field sends the first message to the agent and opens the chat; no portrait or scripted code scenery any more ([ADR-0051](../../decisions/0051-calm-chat-layout-and-motion.md)) |
| Prompts page (A4, Lot A) | Real, read-only (2026-11-01, checked with the real model on 2026-11-01) | Reads the real registry (`GET /api/prompts`, text, diff); "Essayer dans cette conversation" sets a system version for the open conversation only (`POST /api/sessions/{id}/prompt-trial`), with a badge in the chat. The registry is never written by the web server: activating a version for everyone stays `sensai-prompt use` ([ADR-0055](../../decisions/0055-prompt-versions-in-the-web.md)). Since 2026-11-01 (branch `feat/fewshot-visible`), the A7 card on that page is real: examples file, threshold and example questions (`GET /api/fewshot`); the chat shows under an answer which example inspired it. Demo data only with the simulated engine |

## Update of 2026-10-18 (historical)

> The real server existed from this date ([ADR-0035](../../decisions/0035-serveur-web-reel.md)):
> `sensai-web` served the interface and the API of the real agent. With it,
> these were **real**: the chat (streamed model answer), reasoning and tool
> calls, confirmations before writing or running, interruption, branches (one
> new session per branch), RAG sources, the cache, input guardrails, `/…`
> commands and sessions (shared with the CLI). Still **simulated** then: token
> usage and compression, eval scores, agent relays, personas, form questions,
> the share link, and the agents, quality, prompts and planning pages.

## State on 2026-10-14 (historical, before the server)

Written for the mid-project demo, on branch `lot-d/interface-web` (created
from `main`). "Real" meant the Python code in `src/sensai/`; team branches not
yet merged were not counted. Decision context:
[ADR-0020](../../decisions/0020-interface-web-simulee.md).

### Principle

- **Real**: the interface itself (`frontend/`), its navigation, forms, local
  exports, branches and interruptions, which work on the simulated engine, and
  the event contract (`frontend/src/contract/`).
- **Simulated**: the engine. It replays scenarios written in advance
  (`frontend/src/engine/scenarios/`), picked by keywords. No model is called,
  no project file is read, no network is used.
- A "Moteur simulé" badge stays visible on every page.

### By feature

| Feature | In the interface (demo) | In the Python repo |
| --- | --- | --- |
| B1 CLI | Chat with simulated streaming | **Real**: `cli.py`, `core/ollama_client.py`, `core/history.py` |
| M1 Sessions and profile | Memory page (profile editable in page memory, demo sessions); resume scenario | **Real**: `knowledge/memory.py` |
| M2 Token budget | Gauge and alert at 80 %, scripted compression | Not started |
| M3 Structured memory | Facts shown, static | Not started |
| M4 State document | Artifact panel updated by scenario, changed section highlighted | Not started |
| T1 MCP | Scripted `mcp.fetch` call | Skeleton: `tools/mcp_tool.py` ("À FAIRE") |
| T2 Sandbox | Scripted failure then fix | Skeleton: `execution/sandbox.py` |
| T3 Web search | Two scripted results (real links, no request) | Not started |
| T4 File access | Listing and deletion in an "allowed" folder, scripted | Not started |
| T5 Structured output | Static example accepted / rejected by a schema | Not started |
| R1 RAG | Scenario sources: `cli.py:112-116` is the README example; other paths, lines and scores are illustrative | **Real**: `knowledge/rag.py`, `tools/rag_tool.py` |
| R2 Advanced RAG | **Partial**: only one score per passage; no reranking or filter shown | Not started |
| A1 ReAct | Scripted Thought / Action / Observation reasoning | Contract only: `core/agent.py` |
| A2 Multi-agents | Scripted relay | Not started |
| A3 Confirmation | Allow / Deny card; **denying really changes the scenario's flow** | Skeleton: `execution/human_in_loop.py` |
| A4 Prompt versions | v1 texts **real** (files in `prompts/`); v2 = demo draft; "Mettre en service" only changes page state, not `prompts/versions.json` | **Real**: `knowledge/prompt_versions.py`, `sensai-prompt` |
| A5 Persona | Two demo agents, switchable during a session | Not started |
| A6 Semantic cache | Scripted "réponse servie depuis le cache" pill | Not started |
| A7 Prompt optimisation | Simulated score bars | Real since 2026-11-01: few-shot card (`GET /api/fewshot`) and "Inspirée de l'exemple" under the answer |
| EV1 Evaluation | Scripted relevance and faithfulness scores | Not started |
| EV2 Guardrails | Scripted "secret masqué" card | Skeleton: `execution/guardrails.py` |
| EV3 Journal | Journal page computed from calls **really emitted** by the simulated session (the data is real, the engine producing it is simulated) | Not started (`observability/` empty) |
| EV4 Adversarial tests | Simulated list of 5 attacks, including one admitted weakness | Not started |
| X1 Web interface | **Real interface** (`frontend/`) on a simulated engine; chat welcome where the agent greets; AI visual: portrait supplied by the team (**not** a 3D model; image rights to check, see [ADR-0021](../../decisions/0021-visuel-3d-et-animations.md)). Poster-style home ([ADR-0025](../../decisions/0025-hero-de-l-accueil-en-affiche.md)); **the live code analysis (typed code, bug judged then fixed) is a scripted animation**: three snippets written in advance, no project file is read ([ADR-0026](../../decisions/0026-univers-code-anime.md)); `HttpEngine` typed but not wired | Web backend not started (`web/` empty). Throw-away prototype tested: `docs/conception/web_facade_spike.py` (15 tests, fake Ollama), see [web-api-alignement.md](web-api-alignement.md) |
| X2 Branches | **Real on the interface side**: edit, navigable branches, interruption, redirection. `HttpEngine` answers branches with an explicit error | Backend not started |
| X3 Export | **Real on the interface side**: JSON and Markdown downloaded locally, PDF through browser printing; **fake** share link (`codesensei.example`) | Backend not started |
| X4 Questions and forms | Real form; answers are really reused in the scripted answer | Backend not started |
| X5 Planning | Editable task list; **no task runs** | Not started |

### What the 2026-10-14 demo proved, and what it did not

- ✅ It proved the user journey was designed end to end and that each feature
  had a clear place in the interface.
- ✅ It proved the event contract was enough to show reasoning, confirmations,
  forms, metrics and branches.
- ❌ It did **not** prove that the real engine can produce these events, how
  fast, or with what answer quality.
- ❌ It did **not** understand free text: a text matching no scenario got a
  fallback answer.
- ❌ Quality, cache and performance numbers shown were examples, **not
  measurements**.

### What we said at the mid-project demo

« L'interface est réelle ; le moteur est simulé pour cette démo, car le
backend web n'est pas encore branché. Le contrat entre les deux est écrit et
testé : le brancher revient à remplacer un adaptateur. »
