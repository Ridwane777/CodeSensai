# User stories - [T4] File Access within Permissions

Tools `read_file` and `write_file`, permission layer
`execution/file_permissions.py`, decision in [ADR-0011](../decisions/0011-file-permissions.md).

Personas: Camille, the developer, and Marc, the lead who configures the tool
for the team ([persona-and-scenario.md](../design/persona-and-scenario.md)).

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: write after confirmation: ✅ with both models (10 min 39 on CPU, 8 s on GPU).

## US-T4-1 - Let the agent read my project without exposing my secrets
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who asks "explain this module",
**I want** the agent to read my project's files but never `.env`, my keys or `.git`,
**so that** I save time without a secret ending up in the model's context.

**Acceptance criteria:**
- Reading a project file returns its content; a long file is read page by page (`offset`, `limit`).
- Reading `.env`, `*.pem`, `.ssh/…` or `.git/…` is refused with a message that says why.
- Reading `../x`, `/etc/passwd` or a symbolic link that leaves the project is refused.
- A binary or too large file returns a readable error, not a crash.

## US-T4-2 - Approve each write while seeing what changes
> **Update on 2026-11-06:** scenario step **S4**, the fix, approved ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who lets the agent edit her code,
**I want** to see the exact path and a diff before the file is written,
**so that** I can refuse a change I did not want.

**Acceptance criteria:**
- Without a "yes" answer, no file is created or modified (empty answer, closed stdin and timeout count as no).
- The confirmation request shows the full path; for a replacement, a before/after diff.
- An existing file is never overwritten without `overwrite=true`, visible in the request.
- Writing outside the project or to a protected file is refused before the question is even asked.

## US-T4-3 - Limit where the agent can write
> **Update on 2026-11-06:** scenario step **S0**, Marc sets CodeSensai up ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who wants an agent "allowed to read and write in `/src`" for the team,
**I want** to declare separate read and write folders in the config,
**so that** the rest of the project stays read-only.

**Acceptance criteria:**
- With `files.write = ["src"]`, writing in `src/` works, writing to `README.md` is refused, reading it is still possible.
- Adding patterns to `files.deny` protects more files; the default patterns cannot be removed.
- An unknown key in `files` is a configuration error, not ignored.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-T4-1 | ✅ | `tools/read_file_tool.py`, `execution/file_permissions.py` | `tests/tools/test_file_tools.py` (`read_pages_long_files`, `read_refuses_secrets_and_escapes`, `read_too_large`), `tests/execution/test_file_permissions.py::test_symlink_pointing_outside_is_refused` |  |
| US-T4-2 | ✅ | `tools/write_file_tool.py` | `tests/tools/test_file_tools.py` (`nothing_is_written_without_confirmation`, `describe_call_shows_a_diff_when_replacing`, `write_never_overwrites_by_default`) |  |
| US-T4-3 | ✅ | `execution/file_permissions.py` | `tests/execution/test_file_permissions.py` (`read_and_write_roots_are_separate`, `extra_deny_patterns_add_to_defaults_never_replace`, `unknown_setting_is_an_error`) |  |
