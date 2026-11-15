# ADR-0011 - File access: a per-path permission layer, deny by default

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-13
- **Deciders**: Meric (Workstream B); awaiting team review
- **Workstream**: B (`read_file` / `write_file` tools); A (the agent exposes them); D (the web interface will display the confirmation)

## Context
[T4] asks for file-system operations **and** a permission layer that says
which files the agent may read or touch, checked **before** any operation.
The tool gateway (ADR-0006) decides whether a tool *may* run, not which
paths it touches: that part belongs to the file tool. A path is text written
by the model, so potentially influenced by hostile content (prompt injection
in a file that was read).

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| A. Shared permission layer, path **resolved** (`..` and symlinks followed) then compared to allowed folders | Blocks `../../etc/passwd` and outbound links; a single place to test | Check done before opening, not on the open descriptor |
| B. Filter the path text (refuse `..`) | Trivial | Bypassable (symlink, absolute path): false security |
| C. Run file operations in the Docker sandbox (ADR-0012) | Real isolation | The project would have to be mounted in the container; slow; overkill for simple reads |
| D. Confirm every read | Maximum control | Unusable: the agent reads dozens of files |

## Decision
Option A. Root = project folder for reading and writing, extensible through
the `files` section of the config (separate read and write folders). A list
of protected names (`.env`, `.git`, `.ssh`, `*.pem`, keys…) is refused even
inside the root; the config can extend it, never shorten it. `read_file`
(risk `read`) runs without asking; `write_file` (risk `write`) always asks
(A3), shows the exact path and a diff, and **refuses to overwrite** without
`overwrite=true`. Atomic write (temporary file then rename).

## Consequences
- ✅ Escaping the project is impossible via `..`, absolute path or symlink (tested).
- ✅ Secrets are neither readable nor writable, so they do not enter the model's context.
- ✅ The user sees a diff before approving a replacement.
- ❌ TOCTOU window: a symlink created between the check and the open is not detected. Acceptable for a single-user agent; to revisit if the tool runs on a shared machine (open with `O_NOFOLLOW`/`openat`).
- ❌ A core set of protected names is a list: a secret named differently (`config.prod.yml`) is readable. The EV2 filters then mask credentials in the content, which limits the leak without eliminating it.
- ❌ `read_file` does not ask for confirmation: a project file containing an injection is read without the user seeing it. Mitigated by the "untrusted data" marking and `confirm_after_untrusted` (subsequent writes confirmed).
- ❌ No binary, UTF-8 only, 1 MB maximum: a limit of the tool, not of the layer.
- Follow-up: tests `tests/execution/test_file_permissions.py` and `tests/tools/test_file_tools.py`; to revisit if the tool serves several users.
