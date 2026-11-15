# ADR-0007 - Session and profile persistence: SQLite in ~/.sensai, sessions per project

Date: 2026-10-11
Workstream: C (impacts A and D)
Status: Accepted (2026-11-01, approved by the team)

## Context
Feature [M1] asks for two things: find a conversation's history again from
one CLI session to the next, and a user profile (preferences, instructions)
injected at startup. ClickUp Definition of Done: closing and reopening the
CLI keeps the history and the preferences. Detailed needs are in
[the M1 user stories](../user-stories/M1-session-persistence.md).

Constraints:
- **The web will read the same sessions.** Workstream A's API contract
  provides `GET /api/sessions` and `GET /api/sessions/{id}`, and Workstream
  D has a task "Reopen a past conversation". Storage must therefore be
  readable from Python code, by a process other than the CLI.
- **History is sensitive.** It contains the user's code, their questions,
  and potentially secrets pasted by mistake. It must not be able to end up
  in a Git repository.
- **A developer works on several projects.** Resuming "the last session"
  must not reopen another project's conversation.
- Standard library preferred: the requirements list `sqlite3` as an allowed
  dependency.

To settle the location and startup behavior, we looked at how existing command-line coding agents
do it: sessions stored per project under the user's home folder, a new session by
default with `--continue` to resume, profile as global and per-project
instruction files.

## Considered options

**Session storage**
- **SQLite** - chosen. Standard library; a save is a transaction, so a CLI
  killed mid-write does not leave a half-written session; the web server can
  read while the CLI runs; listing sessions is a query. Lost: the database
  cannot be read by eye without a tool (the `sqlite3` command line is
  enough).
- One JSON file per session - readable and easy to debug, but non-atomic
  writes without precautions, and listing sessions means opening every file.
- A single JSON file - simplest to code, but rewritten in full on every
  message, and one corrupted file loses all sessions.
- Append-only JSONL, like other command-line agents - robust to interruptions, but
  `History.drop_last()` removes a turn after an error: an append-only file
  would keep that turn, or require extra undo logic.

**Data location**
- **`~/.sensai/`, sessions tied to the project** - chosen. The project is
  the folder the CLI is launched from (absolute path). Outside any
  repository, so never committable, and contexts from different projects do
  not mix. Lost: one more column and filter.
- `~/.sensai/` with no notion of project - simpler, but all sessions of all
  projects in a single list, and "resume the last one" may reopen the wrong
  project.
- A `.sensai/` folder inside the project - separated per project with no
  code, but one forgotten `.gitignore` is enough to commit the history.

**Startup behavior**
- **Resume the project's last session** - chosen. Directly meets the
  Definition of Done and US-M1-1. `--new-session` starts from scratch,
  `--session <id>` resumes a specific session.
- New session by default and `--continue` to resume (the usual choice of command-line agents) -
  avoids context lingering from one topic to the next, but the DoD can only
  be demonstrated with an option. Rejected to match the DoD; remains
  defensible if usage shows that automatic resume gets in the way.
- New session only, `--session <id>` to resume - no shortcut to the last
  session.

**Profile**
- **A global `profile.json`, editable by commands in the CLI and by hand** -
  chosen. Fields `name`, `instructions`, `preferences` (list). Commands
  `/remember <text>`, `/profile`, `/forget`. Demonstrable live. Lost: a
  single profile for all projects.
- Global profile + per-project profile (per-project instruction file) - closer to the
  real need, but two levels to merge, test and explain. Rejected for time;
  it is the natural next step.
- Free-form Markdown injected as is - no schema, but no adding or removing
  a single preference.
- JSON edited by hand only - the least code, but not very telling in a demo.

**Protecting files on the machine**
- **Folder in `700`, files in `600`, only if CodeSensai creates the
  folder** - chosen. Other accounts on the machine read neither the history
  nor the profile. An existing folder is not modified: `--data-dir` may point
  to the user's home folder, whose permissions must not be changed.
- System default permissions (umask, often `755`/`644`) - nothing to code,
  but any account on the machine can read the user's code and questions.
- Database encryption - also protects a disk copy, but requires a
  dependency (SQLCipher) and key management; disproportionate for a local
  tool.

**Deleting a session**
- **No command in the CLI** - chosen. Reference command-line agents do
  without it: the ones we looked at do not offer one, to our knowledge
  (sessions as files deleted by hand, sometimes an automatic purge after a
  delay). Some have `/chat delete`, but only for explicitly saved
  conversations. Per-conversation deletion is a web-interface use case
  (hosted chat assistants). `SessionStore.delete()` exists in the code: Workstream D
  can expose it in the web interface without other changes.
- A `/delete <id>` command - useful to erase a conversation where a secret
  was pasted, but redundant with deleting `~/.sensai` for CLI use, and one
  more command to test.

**Retention period**
- **Purge at startup of sessions with no message for 30 days,
  configurable** - chosen. Same default as the command-line agents we looked at. The reference is
  `updated_at`, the date of the last exchanged message. `--retention-days` or
  the `retention_days` key in `config.json` change the duration; `0`
  disables the purge. This is the answer to secrets pasted by mistake: they
  do not stay on disk indefinitely.
- `created_at` as reference - rejected: an active conversation started 31
  days ago would be deleted mid-work.
- "Last opened" as reference - rejected: with resume by default, every
  launch opens the last session, which would therefore never be purged; and
  it would mean writing to the database on every open.
- No purge - nothing to code, but unlimited retention of potentially
  sensitive data.
- Keep a trace of deleted sessions to explain their absence - rejected: that
  would keep a trace of what we wanted to erase. The "unknown session"
  message mentions the purge as a possible cause.

## Decision
- Sessions in a SQLite database `~/.sensai/sessions.db` (folder changeable
  via `SENSAI_HOME` or `--data-dir`), each session tied to the project's
  absolute path.
- At startup, the CLI resumes the last non-empty session of the current
  project; `--new-session` and `--session <id>` change this behavior.
- Profile in `~/.sensai/profile.json`, editable via `/remember`, `/profile`,
  `/forget` or by hand, added to the system prompt at every startup.
- **The system prompt is not saved with the session**: it is rebuilt at
  every startup (prompt file + profile). Otherwise, fixing the prompt or the
  profile would have no effect on old conversations.
- A session is only saved after a complete model response: a failed turn,
  removed by `drop_last()`, never reaches the database.
- When a session is resumed, an instruction read from
  `prompts/memory_prompt.txt` (since A4: active version of the `memory`
  prompt, [ADR-0010](0010-prompt-versioning.md)) is added to the system
  prompt: the history is real and the model must use it. Added after real
  trial runs, where `llama3` then `qwen3-coder:30b` denied having any memory
  ([docs/performance/M1-sessions.md](../performance/M1-sessions.md)).
- The data folder is created in `700`, `sessions.db` and `profile.json` in
  `600`. A folder that already exists keeps its permissions.
- No session deletion from the CLI; `SessionStore.delete()` remains
  available for the web interface.
- At startup, sessions with no message for more than 30 days
  (`--retention-days`, `retention_days`, `0` = never) are deleted, with a
  message; the session requested via `--session` is spared. A `VACUUM`
  follows the purge so that deleted text does not remain in the file.

## Consequences
- ✅ M1's DoD is met without an option: closing and reopening the CLI
  resumes the conversation and the profile.
- ✅ Workstream D can list and reopen sessions by calling the same module
  (`knowledge/memory.py`), without depending on the CLI.
- ✅ No dependency added to `requirements.txt`.
- ✅ The demo model relies on the resumed history ("Yes, you had a login
  bug…") thanks to the resume instruction.
- ✅ Possible basis for [M3] External Structured Memory, if the team ever
  adopts it: the SQLite database already exists.
- ❌ History is stored **in plain text** on the user's disk. A secret pasted
  into the chat stays there. Secret filtering belongs to Workstream B's
  guardrails ([EV2]); we will need to decide whether they also apply before
  saving.
- ✅ Other accounts on the machine cannot read the history or the profile.
- ❌ A `~/.sensai` folder created before this change, or chosen by the user,
  keeps its original permissions: `chmod 700 ~/.sensai` must be done by
  hand.
- ❌ To erase a single conversation from the CLI, you have to go through
  `sqlite3`; only full erasure (deleting `~/.sensai`) is simple.
- ✅ Limited retention: inactive data disappears on its own.
- ❌ A conversation you meant to resume after more than 30 days is lost; the
  startup message and the `0` option limit the surprise without preventing
  it.
- ❌ A purged session and a mistyped id give the same message: the CLI
  cannot tell which of the two causes applies.
- ❌ A project moved or opened from another path appears as another
  project: its old sessions are no longer resumed automatically (they remain
  reachable via `--session <id>`).
- ❌ A single profile for all projects; the per-project profile is the next
  step.
