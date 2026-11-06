# User stories — index

Every story is written for one of the two personas of the scenario
([persona-and-scenario.md](../conception/persona-and-scenario.md)):

- **Camille**, the developer who takes over an unfamiliar Python code base and
  may not send it to a cloud API (primary persona);
- **Marc**, the tech lead who sets CodeSensei up for the team: prompts,
  evaluation, adversarial tests, permissions, scheduled tasks (secondary
  persona).

Roles were rewritten on 2026-11-01 to name these personas (they used to say
"developer", "user", "team member", "reviewer"); acceptance criteria and
dated statuses were not changed. Feature → story → ADR → code → tests →
scenario step: [traceability.md](../conception/traceability.md). Features
dropped or changed along the way, with the stories withdrawn, replaced or
modified: [traceability.md](../conception/traceability.md#features-dropped-or-changed-along-the-way).

Format: "As … I want … so that …" plus observable acceptance criteria, at
least two stories per feature (subject requirement).

**Code audit of 2026-11-01.** Every story was checked against the code and
the automated tests, not against the earlier statuses. Each story file ends
with a "Code audit on 2026-11-01" table (code path, test, what is missing).
"Implemented" means every acceptance criterion has code **and** a test that
proves it; a story that depends on what the model chooses to say is counted as
partial.

| Feature | File | Persona | Implemented / total |
| --- | --- | --- | --- |
| B1 Base agent (CLI, Ollama, loop) | [A1-reasoning-loops.md](A1-reasoning-loops.md), [T1-tool-calling-mcp.md](T1-tool-calling-mcp.md) | Camille | 3 / 6 (shared with A1 and T1) |
| A1 Reasoning loop | [A1-reasoning-loops.md](A1-reasoning-loops.md) | Camille | 2 / 4 |
| A2 Multi-agent orchestration | [A2-multi-agent-orchestration.md](A2-multi-agent-orchestration.md) | Camille | 3 / 4 |
| A3 Human in the loop (CLI and browser) | [A3-human-in-the-loop.md](A3-human-in-the-loop.md) | Camille | 7 / 7 |
| A4 Prompt versioning | [A4-prompt-versioning.md](A4-prompt-versioning.md) | Marc | 5 / 5 |
| A5 Persona | [A5-persona.md](A5-persona.md) | Marc (configuration, restrictions), Camille (switching) | 5 / 5 (stories 3 and 5 withdrawn, ADR-0056) |
| A6 Semantic cache | [A6-semantic-cache.md](A6-semantic-cache.md) | Camille | 3 / 3 |
| A7 Prompt optimisation (few-shot) | [A7-prompt-optimization.md](A7-prompt-optimization.md) | Marc (examples), Camille (answers) | 2 / 2 |
| M1 Session persistence | [M1-session-persistence.md](M1-session-persistence.md) | Camille | 3 / 3 |
| M2 Context and token budget | [M2-token-budgeting.md](M2-token-budgeting.md) | Camille | 5 / 5 |
| M3 Structured memory | [M3-structured-memory.md](M3-structured-memory.md) | Camille | 3 / 3 |
| M4 State document | [M4-state-document.md](M4-state-document.md) | Camille | 3 / 3 |
| R1 Basic RAG | [R1-basic-rag.md](R1-basic-rag.md) | Camille | 4 / 4 |
| R2 Advanced RAG | [R2-advanced-rag.md](R2-advanced-rag.md) | Camille | 3 / 3 |
| T1 Tool calling and MCP | [T1-tool-calling-mcp.md](T1-tool-calling-mcp.md) | Camille; Marc (plugging an MCP server) | 3 / 6 |
| T2 Sandboxed execution | [T2-sandbox-execution.md](T2-sandbox-execution.md) US-T2-1, US-T2-2 | Camille | 2 / 2 |
| T3 Web search | [T3-web-search.md](T3-web-search.md) US-T3-1 to US-T3-6 (US-T3-5, US-T3-6: isolated search, moved from T2 on 2026-11-02) | Camille; Marc (US-T3-4) | 5 / 6 |
| T4 File access | [T4-file-access.md](T4-file-access.md) | Camille; Marc (write folders) | 3 / 3 |
| T5 Structured output | [T5-structured-output.md](T5-structured-output.md) | Camille | 3 / 3 |
| EV1 Evaluation | [EV1-evaluation-hallucinations.md](EV1-evaluation-hallucinations.md) | Marc | 5 / 5 |
| EV2 Guardrails | [EV2-guardrails.md](EV2-guardrails.md) | Camille; Marc (blocked topics, sharing the agent) | 6 / 7 |
| EV3 Logs and metrics | [EV3-logs-metrics.md](EV3-logs-metrics.md) | Camille | 2 / 2 |
| EV4 Adversarial testing | [EV4-adversarial-testing.md](EV4-adversarial-testing.md) | Marc | 4 / 4 |
| X1 Web interface | [X1-web-interface.md](X1-web-interface.md) | Camille; Marc (server set-up) | 13 / 17 (US-X1-4 replaced, US-X1-6 withdrawn with the 3D layer, ADR-0056) |
| X2 Branching and interruption | [X2-branching.md](X2-branching.md) | Camille | 2 / 3 |
| X3 Export and publication | [X3-export-publication.md](X3-export-publication.md) | Camille | 2 / 3 |
| X4 Questions and forms | [X4-questions-forms.md](X4-questions-forms.md) | Camille | 2 / 2 |
| X5 Scheduling | [X5-scheduling.md](X5-scheduling.md) | Camille (daily summary, from the chat); Marc (night runs, several tasks) | 5 / 5 |

**One file per catalogue feature (2026-11-02).** Features that had two or
three files were merged: T1 (`T1-native-tool-calling.md`, `T1-mcp-integration.md`,
`T1-mcp-web-display.md` → [T1-tool-calling-mcp.md](T1-tool-calling-mcp.md)), A3
(`A3-web-confirmation.md`), X1 (`X1-chat-comfort.md`, and the old index
`X-interface-web.md`) and M2 (`M2-context-management.md`). Stories numbered
"User Story 1, 2" got unique ids (US-T1-3 to US-T1-6, US-M2-1 to US-M2-5); each
title keeps its former name. The web server and tool gateway requirements are
technical, not stories of one feature: they moved to
[architecture/web-api.md](../architecture/web-api.md) and
[architecture/tool-gateway.md](../architecture/tool-gateway.md).

