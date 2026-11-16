# CodeSensai

**A local coding agent that reads your codebase, runs and fixes code in a
sandbox, and asks before it touches anything - on a model you host yourself.**

CodeSensai is a developer agent written in Python 3.12 that talks directly to
[Ollama](https://ollama.com)'s HTTP API, **without an LLM framework**
([ADR-0001](docs/decisions/0001-no-llm-framework.md)). It reads your project
(hybrid RAG with reranking), reasons step by step (ReAct loop on native tool
calling), runs Python in a disposable Docker container, reads and writes
project files, searches the web from an isolated browser, asks for
confirmation before any risky action, masks secrets, keeps sessions, a project
state document and a fact memory, runs scheduled tasks, plugs in MCP tools, and
evaluates itself (LLM judge, adversarial corpus). It ships with a terminal
client and a web interface (React + TypeScript, SSE streaming).

## Highlights

- **No framework, full control**: agent loop, tool registry, Ollama client,
  context budgeting and structured output are plain Python
  (`src/sensai/core/`).
- **Safety by design**: every tool call goes through one gateway - human
  confirmation for writes and execution, secret masking on tool I/O *and* on
  the streamed answer, path allow-lists, timeouts, untrusted-output wrapping
  ([ADR-0006](docs/decisions/0006-tool-gateway.md)).
- **Sandboxed execution**: no network, read-only filesystem, unprivileged
  user, 256 MB, ½ CPU, 10 s default timeout
  ([sandbox](docs/architecture/sandbox.md)).
- **Knowledge**: hybrid RAG (dense `bge-m3` + BM25, RRF, model reranking),
  session persistence, structured fact memory, `SENSAI.md` state document,
  conservative semantic cache, sliding summary under a token budget.
- **Measured, not claimed**: every feature has a reproducible trial script and
  raw results in [docs/performance/](docs/performance/).

Architecture: [docs/architecture/architecture.md](docs/architecture/architecture.md) ·
decisions (59 ADRs): [docs/decisions/](docs/decisions/README.md) ·
documentation map: [docs/README.md](docs/README.md) ·
contributing: [CONTRIBUTING.md](CONTRIBUTING.md).

## Results

All figures come from the linked reports (one run per scenario unless stated).

| What | Result | Source |
| --- | --- | --- |
| End-to-end feature trial, `qwen3-coder:30b` on a 24 GB GPU | **28/28 features work** after reruns (24/28 on the first run) | [trial 2026-11-06](docs/performance/trials/trial-2026-11-06.md) |
| Same trial, `qwen3:8b` on a laptop CPU (no GPU) | 26/28 pass (T5 and A2 fail), 7–11 min per question | [trial 2026-11-06](docs/performance/trials/trial-2026-11-06.md) |
| RAG embedding choice (15 questions, 106 passages) | `bge-m3`: right file first 11/15, top 3 14/15, MRR 0.842 | [R1-rag.md](docs/performance/R1-rag.md) |
| Hybrid RAG + model reranking | first 12/15, top 5 15/15, MRR 0.883 (dense alone: MRR 0.541); held-out set MRR 0.759 | [R2-rag.md](docs/performance/R2-rag.md) |
| Semantic cache (`bge-m3` + rules) | threshold 0.876, 10/39 rephrasings served; cached answer in 1.06 s instead of 16.8 s | [A6-cache.md](docs/performance/A6-cache.md) |
| Adversarial corpus (prompt injection, secret leaks, path escapes…) | 85 cases: 66 handled, 19 known gaps tracked as strict `xfail` | [EV4 report](docs/security/EV4-adversarial-tests.md) |
| Test suite | 1,403 Python tests pass (+19 strict `xfail`, 1 skipped), 229 frontend tests | `pytest -q`, `npm test` |

## Installation

Requirements: Python 3.12 or later, [Ollama](https://ollama.com), and Docker
to run code and search the web (without Docker, these two tools return a
clear error; everything else works).

```bash
ollama pull qwen3:8b
ollama pull bge-m3      # embeddings for project search (R1), ~1.2 GB
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                 # or, exact versions: pip install -r requirements-dev.txt && pip install -e . --no-deps
docker pull python:3.12-slim            # execution sandbox (T2)
docker build -t sensai-browser:latest docker/browser   # search browser (T3), ~1.1 GB, ~12 min
```

`requirements.txt` pins the tested versions of the runtime dependencies,
`requirements-dev.txt` adds pytest and ruff. Licences and replacements:
[docs/dependencies.md](docs/dependencies.md).

## Running

```bash
sensai
# default dev model: qwen3:8b (see docs/decisions/0004-model-and-infrastructure.md)

# qwen3:8b locally, explicitly (Ollama on this machine):
ollama serve &                          # if Ollama is not already running
sensai --host http://localhost:11434 --model qwen3:8b
sensai-web --host http://localhost:11434 --model qwen3:8b   # web interface
# on a laptop without a GPU: 7 to 11 min per question, set "request_timeout": 1800
# (docs/guide/run-and-use.md); team_task (A2) and /structured (T5) fail
# with this model (docs/performance/trials/trial-2026-11-06.md)

# validation on the large model, served by a RunPod pod (the pod's HTTP proxy):
sensai --host https://<pod-id>-11434.proxy.runpod.net --model qwen3-coder:30b
```

The host does not have to be `localhost`: `--host` is enough to point to a
remote Ollama instance. The code does not change, only the configuration.

## How it works

A user message enters a **ReAct loop** (reason, act, observe): the model either
answers or asks for a tool through Ollama's **native tool calling**; the call goes
through a single **gateway** that checks permissions, asks the human before any
write or execution, masks secrets and wraps untrusted output; the result is fed
back to the model, and the loop repeats until it answers or hits its step limit.

```
user -> agent loop (src/sensai/core) -> gateway (confirm, mask, limit) -> tools -> results -> model (Ollama)
                     ^                                                                 |
                     +--------------------- next step ----------------------------------+
```

| Concept | In one sentence | Where |
| --- | --- | --- |
| Agent loop (ReAct) | interleaving reasoning and tool calls lets the model gather facts before answering | [ADR-0003](docs/decisions/0003-native-ollama-tool-calling.md), [architecture](docs/architecture/architecture.md) |
| Tool gateway and guardrails | one choke point for every tool call: human confirmation, secret masking, path allow-lists, prompt-injection wrapping | [ADR-0006](docs/decisions/0006-tool-gateway.md), [tool-gateway.md](docs/architecture/tool-gateway.md) |
| Sandboxed execution | code runs in a throw-away Docker container without network | [sandbox.md](docs/architecture/sandbox.md) |
| Hybrid RAG | dense embeddings (`bge-m3`) and BM25 merged by reciprocal rank fusion, then reranked by the model | [ADR-0032](docs/decisions/0032-hybrid-rag-and-reranking.md), [R2-rag.md](docs/performance/R2-rag.md) |
| Memory | saved sessions, a structured fact memory, a `SENSAI.md` state document, a sliding summary under a token budget | [ADR-0030](docs/decisions/0030-structured-fact-memory.md), [ADR-0045](docs/decisions/0045-token-budget-sliding-summary.md) |
| Evaluation | an LLM judge scores relevance and hallucinations; an adversarial corpus tests the guardrails | [ADR-0019](docs/decisions/0019-llm-judge-evaluation.md), [EV4 report](docs/security/EV4-adversarial-tests.md) |

## Features

Features in six families, each with an ADR, user stories and a measurement.
Full catalogue with usage: **[docs/features.md](docs/features.md)**. Known limits:
**[docs/known-limits.md](docs/known-limits.md)**.

| Family | Features |
| --- | --- |
| Agent (A) | A1 reasoning loop with tools, A2 multi-agent orchestration, A3 human in the loop, A4 prompt versions, A5 personas, A6 semantic cache, A7 automatic few-shot |
| Memory (M) | M1 sessions and profile, M2 token budget, M3 fact memory, M4 project state document |
| Retrieval (R) | R1 search over the project, R2 hybrid retrieval and reranking |
| Tools (T) | T1 MCP client, T2 sandboxed execution, T3 web search, T4 file access, T5 structured output |
| Evaluation (EV) | EV1 answer evaluation, EV2 guardrails, EV3 logs and metrics, EV4 adversarial tests |
| Interface (X) | X1 web interface, X2 branches, X3 export and share links, X4 questions by form, X5 scheduled tasks |

## References

- Yao et al., 2023. *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR. (agent loop)
- Schick et al., 2023. *Toolformer: Language Models Can Teach Themselves to Use Tools*. NeurIPS. (tool use)
- Lewis et al., 2020. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS. (RAG)
- Robertson and Zaragoza, 2009. *The Probabilistic Relevance Framework: BM25 and Beyond*. (lexical retrieval)
- Cormack, Clarke and Buettcher, 2009. *Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods*. SIGIR. (hybrid fusion)
- Chen et al., 2024. *BGE M3-Embedding*. arXiv:2402.03216. (embedding model)
- Greshake et al., 2023. *Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection*. AISec. (gateway threat model)
- Zheng et al., 2023. *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*. NeurIPS. (EV1)
- OWASP Top 10 for LLM Applications, LLM01 Prompt Injection. (EV4)

Model and infrastructure choices: [docs/research/](docs/research/model-choices.md).

## Testing

```bash
pytest -q                              # no model needed; Docker tests are skipped without Docker
pytest -m docker -q                    # sandbox isolation on real containers
python scripts/trial_tools.py --web   # real trial of the tools through the gateway
(cd frontend && npm test)              # web interface
```

## Team

Built by a team of four.

**My contribution (Ridwane777):** project lead; the knowledge layer in
`src/sensai/knowledge/` - RAG over the codebase (indexing, hybrid retrieval,
reranking, document readers for every file format), session memory, the
structured fact memory, the semantic cache, the `SENSAI.md` state document and
prompt versioning - with their agent tools (`search_codebase`, `save_fact` /
`recall_facts`, `update_state`, `schedule_task`, `list_files`, project tests),
the CLI and configuration (`cli.py`, `config.py`, `ui.py`, `sensai-prompt`),
the EV4 adversarial corpus, and most of the architecture, decision (ADR),
business, research and performance documentation, including the reproducible
feature-trial scripts and the trial reports.

- **Christopher Guidibi** ([@Christopher142769](https://github.com/Christopher142769)) -
  web frontend (React/TypeScript), the web server (`src/sensai/web/`) and observability.
- **Meric Gbemetonou** ([@Meric-BG](https://github.com/Meric-BG)) -
  sandbox and code execution (Docker Python/browser/document sandboxes, tool
  gateway, guardrails, human-in-the-loop), file and web-search tools,
  scheduling, LLM-judge evaluation.
- **Fresnel Satignon** ([@fresnel-cyber](https://github.com/fresnel-cyber)) -
  agent core (`src/sensai/core/`: ReAct loop, Ollama client, history,
  structured output), personas, few-shot examples, context compression,
  sub-agent delegation and team handoffs; legal and dependency documentation.
