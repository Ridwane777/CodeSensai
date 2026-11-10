# ADR-0018 — Adversarial tests: known gaps are strict expected failures

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Meric (Workstream B); awaiting team review
- **Workstream**: B (tested defenses); A (agent loop); D (web interface): gaps OUT-14/15 and PERM-15/16 touch their code

## Context
[EV4] requires testing the defenses against attacks. The first corpus
(`tests/adversarial/`, [report](../security/EV4-adversarial-tests.md)) found
attacks that get through today: 21 out of 85. We must decide what to do with
these cases: delete them to keep CI green, leave them failing, or keep them
visible without breaking the other workstreams' work.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| A. "Normal" failing case (red) | Honest, impossible to forget | Blocks CI and the other workstreams' PRs for gaps Workstream B is not allowed to fix in full (`agent.py`, `cli.py`) |
| B. Delete or weaken the failing cases | Green CI | Hides the weaknesses: the opposite of EV4's goal |
| C. `xfail(strict=True)` asserting the **safe** behavior, with cause and file:line in the reason | Green CI, gap visible on every run, and the test breaks (XPASS) the day the hole is closed: it must be reclassified | An `xfail` becomes routine: the list must be read |
| D. Separate gap file, outside the tests | No noise | Guaranteed drift between the file and the code |

## Decision
Option C. Each known gap is a corpus case with `secure` (the outcome of a
fixed defense) and `gap` (the cause with file:line). The generated table
(`docs/performance/data/EV4-adversarial-results.md`) is versioned and checked
by a test, as is its copy in the report.

Two families are declared **out of scope** for detection: a secret or an
instruction encoded in base64, and homoglyphs from other scripts
(INJ-05, 06, EXF-07, 08). Patterns cannot cover them; the countermeasure is
the readable confirmation, the network-less sandbox and `confirm_after_untrusted`
(already stated in `docs/architecture/tool-contract.md`). These cases stay in the corpus,
marked as known gaps.

## Consequences
- ✅ Weaknesses stay visible on every run and do not block the other workstreams.
- ✅ Fixing a gap without reclassifying its case breaks CI: the report cannot silently lie.
- ❌ 21 `xfail` in the suite: people can get used to seeing them. The report ranks the gaps by severity to prevent this.
- ❌ Declaring base64 and homoglyphs out of scope accepts a known bypass of detection; only defense in depth (confirmation, sandbox) limits it.
- ❌ Line numbers cited in the reasons drift when the code changes; a test only checks that the file and line exist, not their meaning.
- Follow-up: revisit when the CLI wires in the guardrails (OUT-15) or when a tool opens links (NET-08, becomes blocking). Fixing a gap = switch its case to OK in `corpus.py` and regenerate the table.
