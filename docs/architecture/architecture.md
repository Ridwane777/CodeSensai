# Architecture - CodeSensai

Status as of 2026-10-14 (`main`, after #73). Decisions live in
[decisions/](../decisions/README.md); this document describes what the code does.

## Use case
A solo developer (or a small team) on a long-running project who wants an
assistant that can: remember the code context from one session to the next,
run and fix code autonomously, and explain its reasoning transparently -
while asking for confirmation before any risky action and never leaking
secrets.

## Overview

```
 sensai (CLI)        sensai-schedule (X5)        web interface (Workstream D, upcoming)
      │                     │                          │
      └──────────┬──────────┴──────────────────────────┘
                 │  the same events: Token, Thought, ToolCall, ToolReturn, Error, Done
                 ▼
        ReAct agent - core/agent.py                         Workstream A (A1)
        calls the model → reads tool_calls → calls a tool → repeats (6 calls max)
                 │  Ollama native tool calling (ADR-0003)
                 ▼
        Gateway - execution/gateway.py                      Workstream B (ADR-0006)
        risk policy · argument validation · EV2 guardrails ·
        A3 confirmation · timeout (120 s) · result sanitizing and validation
                 │
                 ▼
        Tool registry - core/tools.py + registry.py         shared Tool contract (ADR-0002)
   ┌─────────────┬──────────────┬──────────────┬──────────────┬─────────────────┐
 run_code      read_file      write_file     web_search     search_codebase
 (T2, Docker)  (T4)           (T4)           (T3, Chromium  (R1, Workstream C,
                                              Docker, Bing)  added by the CLI)
                 │
                 ▼
        Ollama (raw HTTP, core/ollama_client.py): qwen3:8b in dev,
        qwen3-coder:30b and bge-m3 on a RunPod pod for validation (ADR-0004)
```

Around the loop:
- **Memory** (`knowledge/memory.py`, M1): sessions and profile in
  `~/.sensai` (SQLite), restored at startup; the profile is added to the
  system prompt.
- **RAG** (`knowledge/rag.py`, R1): project index in `~/.sensai/rag.db`,
  opened on the first question; the best passages are attached to each
  question, and the `search_codebase` tool lets the agent search on its own
  (ADR-0009, ADR-0013). PDFs, Office documents and EPUBs are converted to
  Markdown in a `sensai-docs` container (`execution/sandbox/document_sandbox.py`)
  before indexing, and `read_file` reads them the same way;
  `knowledge/documents.py` identifies a file's type from its content (ADR-0034). Since R2 (`knowledge/retrieval.py`, ADR-0032), each
  search fuses embeddings and BM25 (RRF), then the chat model
  reranks the top 10 passages.
- **State document** (`knowledge/state_document.py`, M4): `SENSAI.md` in
  the project, added to the system prompt, edited section by section by
  the `update_state` tool; log and undo in `~/.sensai/state/`
  (ADR-0029).
- **Fact memory** (`knowledge/facts.py`, M3): entity, attribute, value
  triples in `~/.sensai/memory.db`, saved by `save_fact`
  (confirmed) and retrieved by `recall_facts`; the system prompt lists the
  known entities (ADR-0030).
- **Web server** (`web/runtime.py`, `web/server.py`, `web/cli.py`, X1):
  `sensai-web` builds the same agent as the CLI and exposes it over HTTP (SSE
  stream for a turn, confirmation, interruption, branches, export); it also
  serves the `frontend/` interface (ADR-0035).
- **Answer cache** (`knowledge/cache.py`, A6): questions, answers and
  fingerprints of the files read, in `~/.sensai/cache.db`; a close question
  (bge-m3, threshold 0.90, no differing action or name) gets the answer without
  a chat model call (ADR-0033).
- **Versioned prompts** (`knowledge/prompt_versions.py`, `prompts/`, A4):
  the agent loads the active version of each prompt (ADR-0010).
- **Team tools**, outside conversations: `sensai-prompt` (A4),
  `sensai-eval` (EV1, LLM judge, ADR-0019), the adversarial corpus
  `tests/adversarial/` (EV4, ADR-0018).

## Components and responsibilities

| Component | File(s) | Workstream | Role |
|---|---|---|---|
| Ollama client | `core/ollama_client.py` | A | Raw HTTP calls, streaming, tools in the `tools` field |
| History | `core/history.py` | A | Conversation context sent to the model |
| Agent (ReAct) | `core/agent.py` | A | Tool-calling loop, at most 6 model calls per turn |
| Events | `core/events.py` | A | What a turn emits - CLI ↔ web contract ([api-contract.md](web/api-contract.md), [web-api.md](web/web-api.md)) |
| Tool contract, registry | `core/tools.py` | A | `Tool` protocol, `ToolRegistry` |
| Shared registry | `registry.py` | all | Tools offered to the CLI and the scheduler: one line per tool |
| Gateway | `execution/gateway.py`, `tool_policy.py`, `tool_validation.py`, `output_sanitizer.py` | B | Every tool call goes through it ([tool-contract.md](tool-contract.md)) |
| Confirmation | `execution/human_in_loop.py`, `web_confirmation.py` | B | Terminal confirmer; broker for the web (ADR-0015) |
| Guardrails | `execution/guardrails.py` | B | Masking of secrets and personal data (EV2) |
| File permissions | `execution/file_permissions.py` | B | Allowed folders, sensitive files refused (ADR-0011) |
| Sandboxes | `execution/sandbox/` | B | Python and Chromium in disposable containers ([sandbox.md](sandbox.md)) |
| Tools | `tools/*.py` | B, C | `run_code`, `read_file`, `write_file`, `web_search`, `search_codebase`, `update_state`, `save_fact`, `recall_facts` |
| Scheduler | `scheduling/`, `schedule_cli.py` | B | Interval tasks, unattended ([scheduling.md](scheduling.md)) |
| Evaluation | `eval/` | B | LLM judge and hallucination detection ([EV1](../performance/EV1-evaluation.md)) |
| Memory, RAG, prompts | `knowledge/` | C | Sessions and profile, project index, prompt registry |
| Configuration | `config.py` | A | CLI argument > `config.json` > default; validates the `tools` and `files` sections |
| Web interface | `web/` | D | Upcoming: facade over the same core (ADR-0005) |
| External MCP tool | `tools/mcp_tool.py` | D | Skeleton: to be written |
| Observability | `observability/` | D | Upcoming: turn log, feeds the interface |

## Interfaces - the contracts between workstreams

Every capability exposed to the agent implements the `Tool` protocol
(`core/tools.py`):

```python
class Tool(Protocol):
    name: str
    description: str
    parameters: dict          # JSON Schema of the arguments
    def run(self, **kwargs) -> ToolResult: ...
```

A tool also declares its `risk` (`read`, `network`, `write`, `execute`):
with no declared risk, the gateway treats it as an execution. The agent never
receives the raw registry, only the gateway: the gateway decides whether a call
goes out, with which confirmation, and what comes back to the
model. See [ADR-0002](../decisions/0002-shared-tool-registry.md) and
[ADR-0006](../decisions/0006-tool-gateway.md).

Second contract, for the interfaces: an agent turn emits
**events** (`core/events.py`), not text - the CLI displays them, the
scheduler summarizes them in a run report, the web will serialize them to JSON.
See [ADR-0005](../decisions/0005-web-interface-facade.md).

## Interface ⇄ engine contract (proposed)

Workstream D froze the exchange format before having a backend
([ADR-0005](../decisions/0005-web-interface-facade.md),
[ADR-0020](../decisions/0020-simulated-web-interface.md)). It is written in
TypeScript in `frontend/src/contract/` and tested in `frontend/tests/`.
**It is a proposal, to be validated with Workstream A.**

The interface only knows an `Engine` interface:

| Command (interface → engine) | Effect |
|---|---|
| `send`, `interrupt` | send a message; interrupt the current generation |
| `editMessage` | fork from an edited message (branch) |
| `confirm`, `answer` | answer a confirmation request or a form |
| `switchPersona` | switch agent without clearing the history |

The engine answers with a stream of typed events: `turn_start`, `token`,
`thought` / `action` / `observation` (the reasoning), `confirm_request`,
`question`, `usage`, `compression`, `artifact_patch`, `rag_sources`,
`web_results`, `guardrail`, `eval_score`, `cache_hit`, `agent_handoff`,
`error`, `done`. Two implementations: `MockEngine` (scenarios, used by the
demo) and `HttpEngine` (SSE skeleton, not wired; routes `/messages`,
`/interrupt`, `/confirm`, `/answer`, `/persona` to be confirmed).

## Why this architecture (summary)

- **`core/` vs `execution/` vs `knowledge/`**: split by
  responsibility, not by person - survives a change in who does what.
- **A mandatory gateway between the agent and the tools**: the
  protections (confirmation, guardrails, timeouts) are written once, and
  no tool can forget them.
- **A shared registry**: a tool wired once reaches the CLI and the
  scheduler; only the policy changes (confirmation on one side, systematic
  refusal on the other).
- **`prompts/` as versioned files, not Python constants**:
  a Base Loop requirement, and the basis of A4.
- **`src/` layout + `pyproject.toml`**: installable package
  (`pip install -e .`), clean imports whatever folder the commands are
  run from.
- **`tests/` mirrors `src/`**: each workstream can check its module without
  starting the whole system.
- **`web/` and `observability/` in the same workstream**: the trace produced by
  one is what the other displays.

## Decided since the first version of this document

- Isolation: Docker, disposable containers ([ADR-0012](../decisions/0012-docker-chromium-sandbox.md)).
- RAG vector storage: SQLite + numpy ([ADR-0009](../decisions/0009-rag-over-the-codebase.md)).
- Ollama native tool calling ([ADR-0003](../decisions/0003-native-ollama-tool-calling.md)),
  used by the loop shipped in #13.

## Known limitations (to fix)

- Since 2026-11-01, tool results reach the model wrapped in
  `<tool_output trust="untrusted">` (`core/agent.py`, `fence_untrusted`; former
  gap EV4-OUT-14, [EV4 report](../security/EV4-adversarial-tests.md)).
