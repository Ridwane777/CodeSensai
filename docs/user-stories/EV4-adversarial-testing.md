# User stories - [EV4] Adversarial testing

Corpus `src/sensai/eval/adversarial.py` (moved from
`tests/adversarial/corpus.py` on 2026-11-01 so the web server can run it; the old
path still re-exports it), tests `tests/adversarial/`, script
`scripts/adversarial_run.py`, report
[`docs/security/EV4-adversarial-tests.md`](../security/EV4-adversarial-tests.md),
decision in [ADR-0018](../decisions/0018-strict-xfail-adversarial-gaps.md).

*Translated from French on 2026-11-01.*

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: adversarial corpus (no model): ✅ 85 cases, 19 known gaps.

## US-EV4-1 - Know what the defences really stop
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who must vouch for the agent's security before the team uses it,
**I want** a corpus of replayable attacks (injection, secret leaks, trapped paths, permission bypass, web search, sandbox),
**so that** I see, attack by attack, what is blocked, masked, flagged or let through, without reading the code.

**Acceptance criteria:**
- `python -m pytest tests/adversarial -q` runs without Ollama, without network and without Docker.
- The corpus has at least 30 attacks with unique ids `EV4-<CAT>-NN`, at least 4 per category.
- Each attack has an expected outcome (blocked, masked, flagged or known gap) and the generated table gives the observed outcome and a verdict.
- Removing a defence (for example the file deny list) makes the cases that target it fail.

## US-EV4-2 - Do not lose a known hole
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who gets a flaw fixed,
**I want** every attack that passes today to be a strict expected failure, with its cause and its file:line,
**so that** I know what to fix first and I am told when a fix makes the case obsolete.

**Acceptance criteria:**
- Each known gap asserts the safe behaviour and gives a reason citing a file and a line.
- Closing a gap makes its test fail (strict XPASS) until the case is reclassified.
- The report ranks the gaps by severity and gives each a concrete fix with an effort marked as an estimate.
- No assertion is weakened to turn green.

## US-EV4-3 - Reproduce the measurements exactly
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who reports on the agent's robustness,
**I want** to rerun a script and get exactly the report's table,
**so that** I can check the document does not contradict the code.

**Acceptance criteria:**
- `python scripts/adversarial_run.py` rewrites `docs/performance/data/EV4-adversarial-results.md` with no date or temporary path: two runs give the same file.
- The script returns a non-zero exit code if a case outside the known gaps fails, or if a known gap has been fixed.
- A test fails if the committed file or the report's table differs from the script's output.

## US-EV4-4 - Rerun the attacks from the web interface
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Update on 2026-11-01:** ◐ tested (pytest on the real routes, vitest on the page), not yet tried in a browser on the real server. The corpus never calls the model, so the model is not involved.

**As** Marc, the lead who shows the defences to the team,
**I want** to see the real corpus results on the Quality page and rerun them with one button,
**so that** I can check, live, that the defences still hold, without opening a terminal.

**Acceptance criteria:**
- With the real server, the Quality page shows the 85 cases (id, attempt, expected, observed, verdict), a summary line (OK, known gaps, regressions, fixed gaps to reclassify, skipped) and the date of the run, or says the rows come from the committed file if the server has not run them yet.
- "Relancer les attaques" calls `POST /api/quality/adversarial/run`, which runs the same corpus as the script (about 0.6 s, measured once on the dev machine on 2026-11-01; no model, Docker replaced by fakes); a second click while a run is in progress gets `409 ALREADY_RUNNING`.
- With the simulated engine, the page keeps a short demo list labelled as simulated.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-EV4-1 | ✅ | `eval/adversarial.py` (85 cases: 45 blocked, 12 masked, 9 flagged, 19 known gaps; OUT-14 fixed on 2026-11-01) | `tests/adversarial/test_corpus.py` (`no_regression_in_the_run`, `report_contains_the_generated_table`) |  |
| US-EV4-2 | ✅ | `eval/adversarial.py` | `tests/adversarial/test_corpus.py` (`every_known_gap_names_its_cause_with_file_and_line`, `cited_lines_exist`); the 20 gaps are strict `xfail` |  |
| US-EV4-3 | ✅ | `scripts/adversarial_run.py` | `tests/adversarial/test_corpus.py` (`results_are_deterministic`, `committed_results_file_is_up_to_date`) |  |
| US-EV4-4 | ✅ | `web/server.py` (adversarial route) | `tests/web/test_journal_quality.py`, `frontend/tests/realFeatures.test.tsx` |  |
