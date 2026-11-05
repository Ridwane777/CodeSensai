# User stories — [T1] External tool (MCP)

Interface: `frontend/`.

CodeSensei scenario: Camille takes over a Python project and wants to follow,
correct and keep track of what the agent does, without reading the code.

**Validation status**: these criteria were first checked **on the simulated
engine** (tests in `frontend/tests/`, [ADR-0020](../decisions/0020-interface-web-simulee.md)).
On 2026-10-18, the interface was wired to the real agent through `sensai-web`
([ADR-0035](../decisions/0035-serveur-web-reel.md)) and tried in a browser
with `qwen3-coder:30b` ([web-reel.md](../performance/web-reel.md)). Each story
carries its status:
✅ checked with the real agent · ◐ partly · 🎭 still simulated · ⏳ not checked yet.
Detail per function: [simule-vs-reel.md](../architecture/web/simule-vs-reel.md).

The other features staged in the demo (A1, A3, M2, T2…) have their own
story files.

Other user stories of the interface: [README.md](README.md).

---

## US-T1-1 — See when the agent uses an external tool
> **Status on 2026-10-18:** ◐ Partly. Every real tool is shown with the same card (checked with `read_file` and `write_file`). However, the server registers no MCP tool: the `mcp.fetch` call is still simulated.
>
> **Status on 2026-10-29:** ◐ Partly. Tools named `mcp_<server>_<tool>` now get an "MCP" badge in the reasoning ribbon ([ADR-0047](../decisions/0047-real-agent-handoffs-in-the-web.md), proposed). Checked by frontend tests only: still not tried with a published MCP server in the web interface.

**As** Camille, the developer who wants to know where a piece of information comes from,
**I want** to see that an external tool was called, with its arguments and its result,
**so that** I can judge how reliable the answer is.

**Acceptance criteria:**
- The call appears in the reasoning with the tool's name (`mcp.fetch`), its arguments, the duration and the result.
- The external tool is presented like any other tool (same card).

## US-T1-2 — Find the external calls in the log
> **Status on 2026-10-18:** ◐ Partly. The Log page lists the real calls (checked with `read_file`), but no real MCP call exists yet.

**As** Camille, the developer auditing a session,
**I want** external tool calls to appear in the log with the others,
**so that** I can reread everything in one place.

**Acceptance criteria:**
- The Log page lists `mcp.fetch` with its arguments, its duration and its state.
- A call still running is marked "en cours".

---

## Part merged from `T1-native-tool-calling.md` on 2026-11-02: T1 — Ollama's native tool calling

> Filed as A2 when it was created; it is the "structured tool calling" part
> of [T1] MCP in the catalogue (A2 is Multi-Agent Orchestration there).
> Choice: [ADR-0003](../decisions/0003-tool-calling-natif-ollama.md).

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../conception/persona-and-scenario.md)).

## US-T1-3 — The agent decides to call a tool without ambiguity (was User Story 1 of T1-native-tool-calling.md)

As **Camille, the developer who lets the agent act on her code**, I want **the model to call tools through a structured format** (no text parsing), so that **every tool call is truly intended and executed without a parsing error**.

### Acceptance criteria

- The model uses Ollama's structured `tool_calls` field, not free text to interpret
- Each tool call is valid JSON with a name and typed arguments
- No ambiguity: one tool call = exactly one action
- Parsing errors do not exist (the model cannot generate text that breaks the interpretation)

## US-T1-4 — The agent drops the tool call if the arguments are invalid (was User Story 2 of T1-native-tool-calling.md)

As **Camille, the developer whose local model sometimes gets the arguments wrong**, I want **the tools to refuse invalid arguments before execution and return a clear error message**, so that **a model bug does not break the system**.

### Acceptance criteria

- If the model calls `search_codebase(query=123)` instead of a string, the tool refuses with an error code
- The error message explains the problem and proposes a correct format
- The agent can read this error and try again with the right types
- No exception escapes beyond the validation layer

---

## Part merged from `T1-mcp-integration.md` on 2026-11-02: T1 — MCP integration (Model Context Protocol)

> Filed as A5 when it was created; MCP is [T1] in the catalogue (A5 is
> Persona there). Decision: [ADR-0041](../decisions/0041-client-mcp-maison.md).

Personas: Marc, the lead who configures the tool for the team, and Camille,
the developer of the scenario ([persona-and-scenario.md](../conception/persona-and-scenario.md)).

## US-T1-5 — The agent uses an external MCP tool with no hard-coded dependency (was User Story 1 of T1-mcp-integration.md)

As **Marc, the lead who plugs the company's own tools into the agent**, I want **the agent to call tools through MCP without changing the agent's core code**, so that **new tools (databases, third-party APIs, etc.) can be plugged in easily, without recompiling**.

### Acceptance criteria

- The MCP tools are registered dynamically at start-up
- The agent sees them in its list of available tools
- The agent can call them like any native tool
- Adding a new MCP tool does not change the agent's core code

## US-T1-6 — A broken MCP tool does not block the agent (was User Story 2 of T1-mcp-integration.md)

As **Camille, the developer whose work must not stop when an MCP server is down**, I want **the agent to continue with the available tools if an MCP server does not answer**, so that **an external dependency does not paralyse the whole application**.

### Acceptance criteria

- The broken MCP tool returns a structured error (not an exception)
- The agent reads this error and continues its reasoning
- The other tools remain available
- The user is told about the problem without it being a crash

> **Status on 2026-10-24:** ✅ Checked with the real CLI and the pod's model,
> with the repository's test MCP server (`tests/tools/fake_mcp_server.py`):
> tools registered at start-up from `config.json`, called by the model on its
> own (`mcp_calc_add` → 5555), with confirmation; a server that cannot be found
> is reported and the agent starts anyway; a key returned by the server is
> masked. Failures during a call (silent, unreadable or crashing server):
> covered by the tests. Not yet tried with a published MCP server.

---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-T1-1 | ◐ | `frontend/src/features/chat/ReasoningRibbon.tsx` (MCP badge) | frontend tests only | Never tried with a real MCP server in the web interface |
| US-T1-2 | ◐ | `observability/journal.py` | `tests/observability/test_journal.py` | Every tool call is logged; no test with a real MCP call in the web |
| US-T1-3 Structured format | ◐ | `core/ollama_client.py`, `core/agent.py` | `tests/core/test_agent.py::test_les_outils_partent_au_format_ollama` | "Parsing errors do not exist" is not true: the model sometimes writes calls as text, which `core/agent.py` parses as a fallback (ADR-0031, A1 US-A1-4) |
| US-T1-4 Invalid arguments refused | ✅ | `execution/tool_validation.py`, `execution/gateway.py` | `tests/execution/test_tool_validation.py` (`wrong_type`, `missing_required_field`), `tests/core/test_agent.py::test_des_arguments_invalides_ne_sont_pas_executes` |  |
| US-T1-5 External MCP tool | ✅ | `tools/mcp_tool.py` | `tests/tools/test_mcp_tool.py` (`les_outils_du_serveur_deviennent_des_outils_de_l_agent`, `appel_d_un_outil_mcp`), `tests/test_cli_rag.py::test_les_outils_mcp_de_la_config_sont_proposes` |  |
| US-T1-6 Broken MCP tool | ✅ | `tools/mcp_tool.py` | `tests/tools/test_mcp_tool.py` (`serveur_introuvable_n_empeche_pas_le_demarrage`, `serveur_qui_plante_pendant_un_appel_rend_une_erreur_sans_lever`) |  |
