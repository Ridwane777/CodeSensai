# Architecture decisions (ADR) — index

One important decision = one numbered file, written when the decision is
made, from [TEMPLATE.md](TEMPLATE.md). An accepted ADR is never rewritten: if
the decision changes, a new ADR replaces it. Full rules:
[AGENTS.md](../../AGENTS.md). **Every ADR adds its row here, in the same PR.**

| No. | Title | Date | Status |
| --- | --- | --- | --- |
| [0001](0001-no-llm-framework.md) | No LLM framework, raw HTTP calls to Ollama | 2026-09-21 | Accepted |
| [0002](0002-shared-tool-registry.md) | A shared tool registry rather than direct calls | 2026-09-21 | Accepted |
| [0003](0003-native-ollama-tool-calling.md) | Ollama's native tool calling rather than parsing ReAct text | 2026-09-22 | Accepted (2026-11-01) |
| [0004](0004-model-and-infrastructure.md) | Model and infrastructure: qwen3:8b in dev, qwen3-coder:30b on RunPod | 2026-09-22 | Accepted |
| [0005](0005-web-interface-facade.md) | The web interface is a facade, not a second agent | 2026-09-25 | Accepted (2026-11-01) |
| [0006](0006-tool-gateway.md) | A gateway enforces permissions, validation and confirmation on every tool | 2026-10-07 | Accepted (2026-11-01) |
| [0007](0007-session-persistence.md) | Session and profile persistence: SQLite in ~/.sensai, sessions per project | 2026-10-11 | Accepted (2026-11-01) |
| [0008](0008-scope-all-features.md) | Scope: implement the 28 catalogue features | 2026-10-11 | Accepted; partly superseded by ADR-0056 |
| [0009](0009-rag-over-the-codebase.md) | RAG on the project: bge-m3, SQLite + numpy, automatic indexing | 2026-10-11 | Accepted (2026-11-01); threshold and ranking superseded by ADR-0032 |
| [0010](0010-prompt-versioning.md) | Prompt versioning: immutable versions in the repo, an "active" bookmark | 2026-10-12 | Accepted (2026-11-01) |
| [0011](0011-file-permissions.md) | File access: permissions by resolved path, deny by default | 2026-10-13 | Accepted (2026-11-01) |
| [0012](0012-docker-chromium-sandbox.md) | Disposable Docker containers for code execution and web search | 2026-10-12 | Accepted |
| [0013](0013-wiring-the-rag-tool.md) | The project search tool reuses the index opened by the CLI | 2026-10-14 | Accepted (2026-11-01) |
| [0014](0014-bing-search-engine.md) | Web search: Bing (HTML page) instead of DuckDuckGo, explicit errors | 2026-10-14 | Superseded by ADR-0040 |
| [0015](0015-synchronous-web-confirmation.md) | Web confirmation: a synchronous broker without changing the gateway contract | 2026-10-14 | Accepted (2026-11-01) |
| [0016](0016-task-scheduling.md) | Scheduling: `sensai-schedule run-due` called by cron, no daemon or dependency, unattended runs refuse any action that needs a confirmation | 2026-10-14 | Accepted (2026-11-01) |
| [0017](0017-search-browser-user-agent.md) | Web search: Chromium presents itself as a regular browser (user-agent) | 2026-10-14 | Accepted (2026-11-01) |
| [0018](0018-strict-xfail-adversarial-gaps.md) | Adversarial tests: known gaps are strict expected failures | 2026-10-14 | Accepted (2026-11-01) |
| [0019](0019-llm-judge-evaluation.md) | LLM-judge evaluation: versioned prompt, per-claim faithfulness, comparable reports | 2026-10-14 | Accepted (2026-11-01) |
| [0020](0020-simulated-web-interface.md) | Web interface developed on a simulated engine, behind a replaceable contract | 2026-10-13 | Accepted (2026-11-01); partly superseded by ADR-0035 |
| [0021](0021-3d-visual-and-animations.md) | Agent visual: the provided portrait, static, with a restrained glow and ribbon | 2026-10-13 | Superseded by ADR-0056 |
| [0022](0022-sse-transport-and-execution-model.md) | One turn = one SSE stream opened by POST; the agent runs in a thread | 2026-10-14 | Accepted (2026-11-01) |
| [0023](0023-web-api-access.md) | Web API access: token, local listening, a single public access | 2026-10-14 | Accepted (2026-11-01) |
| [0024](0024-web-contract-extensions.md) | Extensions to the Lot A contract, and a fallback if they are refused | 2026-10-14 | Accepted (2026-11-01) |
| [0025](0025-poster-style-home-hero.md) | Home hero composed like a poster, without a 3D scene | 2026-10-14 | Accepted (2026-11-01) |
| [0026](0026-animated-code-universe.md) | Animated "code" universe: stop motion, parallax and live bug analysis | 2026-10-14 | Superseded by ADR-0056 |
| [0027](0027-rule-based-input-filter.md) | EV2 input filter: deterministic rules, applied before everything else | 2026-10-14 | Accepted (2026-11-01) |
| [0028](0028-schedule-and-eval-commands-in-chat.md) | `/schedule` and `/eval` in the chat: reusing the existing commands | 2026-10-14 | Accepted (2026-11-01) |
| [0029](0029-project-state-document.md) | Project state document: `SENSAI.md`, updated section by section (M4) | 2026-10-17 | Accepted (2026-11-01) |
| [0030](0030-structured-fact-memory.md) | Structured memory: "entity, attribute, value" facts that the agent maintains itself (M3) | 2026-10-17 | Accepted (2026-11-01) |
| [0031](0031-text-written-tool-calls.md) | Tool calls written as text: read them only when the reply is nothing but that | 2026-10-17 | Accepted (2026-11-01) |
| [0032](0032-hybrid-rag-and-reranking.md) | Advanced RAG: hybrid search (BM25 + embeddings, RRF) and model reranking (R2) | 2026-10-17 | Accepted |
| [0033](0033-conservative-semantic-cache.md) | Cautious semantic cache: bge-m3, "decisive words" rules and a 0.90 threshold (A6) | 2026-10-18 | Accepted; amended by ADR-0056 (off by default) |
| [0034](0034-read-all-file-formats.md) | Read and index any file format: identification by content, MarkItDown in the sandbox, honest answer otherwise (#64) | 2026-10-18 | Accepted (2026-11-01) |
| [0035](0035-real-web-server.md) | Real web interface: FastAPI `sensai-web` server, same agent as the CLI | 2026-10-18 | Accepted (2026-11-01) |
| [0036](0036-structured-output-json-schema-format.md) | Structured output (T5): Ollama's `format` field to constrain the reply to a JSON schema | 2026-10-23 | Accepted |
| [0037](0037-sub-agent-delegation-tool.md) | Multi-Agent Orchestration (A2): delegation to a sub-agent through the `delegate_task` tool, same gateway, bounded depth | 2026-10-24 | Partly superseded by ADR-0038 |
| [0038](0038-specialized-agents-and-handoffs.md) | Multi-Agent Orchestration (A2): specialized agents (explorer, developer, reviewer) and `team_task` hand-off; measured delegation fixes | 2026-10-24 | Accepted |
| [0039](0039-project-grounded-structured-output.md) | Structured output (T5) in two steps: the agent searches with its tools, then the constrained call formats the result | 2026-10-24 | Accepted |
| [0040](0040-duckduckgo-web-search-with-bing-fallback.md) | Web search: DuckDuckGo HTML first, Bing as a fallback (Bing only answered on the first word) | 2026-10-24 | Accepted |
| [0041](0041-in-house-mcp-client.md) | MCP (T1): hand-written stdio client, servers declared in `config.json`, one agent tool per MCP tool | 2026-10-24 | Accepted |
| [0042](0042-configurable-personas.md) | Persona (A5): config-driven profiles, switchable mid-session without losing the context | 2026-10-26 | Accepted |
| [0043](0043-persona-enhancements.md) | Persona (A5): keyword routing, per-persona tool restriction, personas added during a session | 2026-10-27 | Accepted; partly superseded by ADR-0056 |
| [0044](0044-automatic-few-shot.md) | Automated Prompt Optimization (A7): semantic few-shot example selection, dataset format reused from EV1 | 2026-10-27 | Accepted |
| [0045](0045-token-budget-sliding-summary.md) | Token Budgeting & Semantic Compression (M2): token estimation, sliding summary produced by the chat model | 2026-10-27 | Accepted |
| [0046](0046-ask-user-tool.md) | Questions & Forms (X4): an `ask_user` tool, answered through the same blocking mechanism as confirmations | 2026-10-29 | Accepted (2026-11-01) |
| [0047](0047-real-agent-handoffs-in-the-web.md) | Web interface (X1, A2): real `agent_handoff` events, announced when a sub-agent actually starts | 2026-10-29 | Accepted (2026-11-01) |
| [0048](0048-share-links.md) | Export & Publication (X3): share links are random-token snapshots served by `sensai-web` | 2026-10-29 | Accepted; amended by ADR-0056 (off by default) |
| [0049](0049-hand-written-markdown-rendering.md) | Web interface (X1): answers rendered by a small hand-written Markdown renderer, not a library | 2026-10-29 | Accepted (2026-11-01) |
| [0050](0050-real-web-features-on-demand-evaluation.md) | Web interface: M2/M4/A2 data streamed as SSE events, EV1 evaluation on demand, X5 tasks edited from the web but run by `sensai-schedule` | 2026-10-29 | Accepted (2026-11-01) |
| [0051](0051-calm-chat-layout-and-motion.md) | Calm chat: wider column, folded side panel, smooth motion and a visible "working" indicator | 2026-10-31 | Accepted (2026-11-01) |
| [0052](0052-schedule-task-tool.md) | Scheduling (X5): the agent may propose a scheduled task, always on explicit approval | 2026-11-01 | Accepted (2026-11-01) |
| [0053](0053-server-side-turn-journal.md) | Turn journal (EV3): a local SQLite store written by the web server and the CLI | 2026-11-01 | Accepted (2026-11-01) |
| [0054](0054-personas-in-the-web.md) | Personas (A5) in the web: one persona per conversation, held in server memory | 2026-11-01 | Accepted (2026-11-01) |
| [0055](0055-prompt-versions-in-the-web.md) | Prompt versions (A4) in the web: read the registry, try a version in one conversation | 2026-11-01 | Accepted (2026-11-01) |
| [0056](0056-scope-review-features-to-drop-or-limit.md) | Features we drop or limit (completes ADR-0008) | 2026-11-01 | Accepted (all five items applied) |
| [0057](0057-generation-parameters-and-loop-limit.md) | Generation parameters and loop limit come from the configuration | 2026-11-01 | Accepted |
| [0058](0058-filtered-answers-and-context-command.md) | The model's answer is filtered while it streams; /context shows what is sent | 2026-11-01 | Accepted |
| [0059](0059-list-files-tool.md) | A read-only `list_files` tool so the agent can see the project | 2026-11-06 | Proposed |

ADR-0012 (sandbox) was first merged under number 0007, already taken by
session persistence: it was renumbered without changing its content.

ADRs 0020 to 0026 (Lot D, web interface and server) were written on a branch
under numbers 0013 to 0019, taken in the meantime in `main` by other lots.
They were renumbered at merge time, on 2026-10-14, without changing their
content; only the numbers and the links were updated.

ADRs 0001 to 0007 and 0012 follow the old model (no Pros/Cons table or
"Deciders" section). They are not rewritten for that reason: an ADR keeps the
form it had when the decision was made.
