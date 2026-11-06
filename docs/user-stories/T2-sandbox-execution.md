# User stories — [T2] Sandboxed code execution

Tool `run_code` (`tools/sandbox_tool.py`), sandboxes in
`execution/sandbox/`. The isolated web search (`web_search`, same sandbox
family) has all its stories in [T3-web-search.md](T3-web-search.md)
(US-T3-5 and US-T3-6 were US-T2-3 and US-T2-4 until 2026-11-02). Decisions: [ADR-0012 (Docker sandbox)](../decisions/0012-sandbox-docker-chromium.md)
and [ADR-0014 (Bing engine)](../decisions/0014-moteur-de-recherche-bing.md);
known limits: [docs/architecture/sandbox.md](../architecture/sandbox.md).

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../conception/persona-and-scenario.md)).

**Out of scope of these stories:** the self-correction loop (the agent
rereads the error and rewrites the code) belongs to the agent's ReAct loop;
these stories guarantee that the error comes back complete enough for that to work.

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/essais/essai-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `run_code` in the Docker sandbox: ✅ `42` with both models (7 min 43 on CPU, 5 s on GPU).

## US-T2-1 — Run code without putting my machine at risk
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who lets the agent test its code,
**I want** this code to run in a disposable container, with no network and no access to my files,
**so that** my data and my machine are not at risk if the code is buggy or malicious.

**Acceptance criteria:**
- `print("bonjour")` through `run_code` returns `bonjour` on standard output and exit code 0.
- The code sees no file of my project or of my home folder, and has no network access (an outgoing connection fails).
- The container runs without privileges (non-root user, read-only file system except a limited `/tmp`) and is removed after each run.
- An infinite loop is stopped at the timeout (10 s by default, 60 s at most) with a readable `Timeout` error; a memory overrun (256 MB) is reported as such.
- If Docker is missing or broken, the tool returns a readable error (`SandboxError`); it does not crash the agent.

## US-T2-2 — Get a usable error to fix the code
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer whose agent writes a script that crashes,
**I want** the tool to return the error type, its message and the call trace,
**so that** the agent can fix its code and run it again without me stepping in.

**Acceptance criteria:**
- A script raising `ZeroDivisionError` returns `ok=false`, `error_type`, `error_message` and the traceback.
- Standard output and standard error are captured separately; an output that is too long is truncated with a visible `[... clipped ...]` marker.
- The same tool, called again with the fixed code, returns `ok=true`: each call starts from a fresh container, with no state left by the previous one.
- Code that is too big (more than 100 KB) or is not text is refused with a clear message.

---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-T2-1 | ✅ | `execution/sandbox/python_sandbox.py`, `tools/sandbox_tool.py` | `tests/execution/sandbox/test_python_isolation.py`, `tests/execution/sandbox/test_python_sandbox.py`, `tests/tools/test_sandbox_tool.py` |  |
| US-T2-2 | ✅ | `execution/sandbox/python_sandbox.py`, `execution/sandbox/result.py` | `tests/execution/sandbox/test_python_sandbox.py`, `tests/execution/sandbox/test_result.py` |  |
