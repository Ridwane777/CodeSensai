# User stories — [EV3] Journal and metrics

Interface: `frontend/`; journal store:
`src/sensai/observability/journal.py` ([ADR-0053](../decisions/0053-server-side-turn-journal.md), Proposed).

CodeSensei scenario: Camille takes over a Python project and wants to follow,
correct and keep track of what the agent does, without reading the code.

**Validation status**: these criteria were first checked **on the simulated
engine** (tests in `frontend/tests/`, [ADR-0020](../decisions/0020-interface-web-simulee.md)).
On 2026-10-18 the interface was wired to the real agent by `sensai-web`
([ADR-0035](../decisions/0035-serveur-web-reel.md)) and tried in a browser with
`qwen3-coder:30b` ([web-reel.md](../performance/web-reel.md)). Each story has its
status:
✅ checked with the real agent · ◐ partly (or tested, not yet with the real model) · 🎭 still simulated · ⏳ not checked yet.
Detail per feature: [simule-vs-reel.md](../architecture/web/simule-vs-reel.md).

The other features staged in the demo (A1, A3, M2, T2…) have their own
story files.

Other user stories of the interface: [README.md](README.md).

*Translated from French on 2026-11-01; the 2026-10-18 statuses are kept as they were.*

---

## US-EV3-1 — Read back what the agent did
> **Status on 2026-10-18:** ✅ Checked with the real agent: `read_file`, its arguments, 21 ms, "Succès".
>
> **Update on 2026-11-01:** ◐ tested, not yet with the real model. With the real server the page now reads the journal **stored by the server** (`GET /api/journal`, `<data_dir>/journal.db`): it survives a reload and reopening the conversation, includes the CLI's turns, and shows each turn's model time and each tool's server-measured duration (sub-agent tools included). Checked by pytest (scripted model) and vitest.

**As** Camille, the developer who must understand a surprising result,
**I want** the list of tools called during the conversation,
**so that** I can find which step produced what.

**Acceptance criteria:**
- Each call is one line: tool, arguments, duration, state (Succès, Échec, en cours).
- With no call, the page says so and explains how to produce one.
- *(Added 2026-11-01)* With the real server, the journal of the open conversation is still there after reloading the page; secrets in the arguments are masked.

## US-EV3-2 — Spot a reliability or slowness problem
> **Status on 2026-10-18:** ✅ Checked with the real agent: the indicators are computed on the real calls (1 call, 21 ms on average, 0 % failures). The "Tokens utilisés" box was still simulated (0).
>
> **Update on 2026-11-01:** ◐ tested, not yet with the real model. "Tous les outils" view: per tool, calls, failures, mean and max duration over 7 days, all conversations and both interfaces (`GET /api/journal/metrics`), plus the model's turn count and mean/max model time.

**As** Camille, the developer who monitors the agent,
**I want** aggregated indicators (number of calls, mean latency, failure rate),
**so that** I see a drift without reading each line.

**Acceptance criteria:**
- With the simulated engine, the indicators are computed from the calls really emitted during the session: after two calls of 410 ms (failure) and 380 ms (success), the page shows 2 calls, 395 ms and 50 % failures.
- Before any call, the number of calls is 0 and the mean latency and failure rate show "—" rather than a misleading zero.
- *(Added 2026-11-01)* With the real server, the metrics cover every conversation of the last 7 days and include the time spent waiting for the model.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-EV3-1 | ✅ | `observability/journal.py`, `web/server.py` (`/api/journal`), `frontend/src/pages/Journal.tsx` | `tests/observability/test_journal.py`, `tests/web/test_journal_quality.py::test_un_tour_web_ecrit_le_journal`, `tests/test_cli_journal.py` |  |
| US-EV3-2 | ✅ | `observability/journal.py` (metrics), `frontend/src/pages/Journal.tsx` | `tests/observability/test_journal.py`, `frontend/tests/pages.test.tsx` |  |
