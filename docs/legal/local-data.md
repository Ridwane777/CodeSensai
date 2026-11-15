# Data kept by CodeSensai - [M1] sessions and profile

This document describes what each feature stores, where, and the risks that
follow. It is completed by each lot (sandbox, RAG, web) as soon as it stores
or sends data.

The data folder is `~/.sensai` by default (`default_data_dir()` in
`src/sensai/knowledge/memory.py`). It can be changed with `--data-dir`,
`SENSAI_HOME` or the `data_dir` key of `config.json`. Below, `~/.sensai`
stands for that folder (`<data_dir>`).

## What is stored

| Data | File | Content |
|---|---|---|
| Sessions | `~/.sensai/sessions.db` (SQLite) | Every message exchanged (questions, answers, pasted code, attached files in the web chat), the project folder path, a title (start of the first message), creation and modification dates |
| Profile | `~/.sensai/profile.json` | Name, instructions and preferences entered by the user |

The system prompt is not stored.

## Where this data goes

- **M1 sends nothing to an outside service.** The files stay on the user's
  machine, outside the code repository.
- **But a resumed session is sent back to the model.** At start, the whole
  session history is added to the context sent to Ollama. With `--host`
  pointing to a remote server (the RunPod pod of ADR-0004), **the exchanges
  of previous sessions go to that server**, not only the current message.
  For a sensitive conversation, use `--new-session` or a local model.

## Identified risks

| Risk | Current situation | Possible fix |
|---|---|---|
| A secret pasted in the chat (API key, password) stays written on disk | Covered for recognised secrets: the input filter (ADR-0027) masks them before saving; an unrecognised secret is stored in clear | See L3 in the [risk analysis](README.md) |
| Access to the files by another user of the machine | Handled: folder created in `700`, `sessions.db` and `profile.json` in `600` | A pre-existing folder keeps its permissions: `chmod 700 ~/.sensai` by hand |
| Unlimited retention | Handled: sessions without a message for 30 days are deleted at start, followed by a `VACUUM` | Duration configurable (`--retention-days`, `retention_days`); `0` disables the purge, to avoid for sensitive data |
| A conversation deleted from the web sidebar is still in the file | Fixed on 2026-10-29: `SessionStore.delete` now runs `VACUUM`, so the text leaves the file (test `test_deleting_a_session_also_erases_its_text_from_the_file`). Before: `SessionStore.delete` ran a `DELETE` without `VACUUM`: the text stayed in the free pages of `sessions.db` until the next retention purge that removed at least one session | None needed since the fix; for a file from before 2026-10-29, run `sqlite3 ~/.sensai/sessions.db VACUUM` once (L11 of the [risk analysis](README.md)) |
| History committed by mistake | Ruled out: the data is outside the repository by default | Do not point `--data-dir` to a versioned folder |

## User's rights over their data

Everything is local and under their control:
- view: `/sessions`, `/profile`, the Memory page of the web interface, or
  open the database with `sqlite3`;
- erase preferences: `/forget`;
- erase one conversation: delete button in the web chat sidebar (see the
  `VACUUM` limit above, fixed on 2026-10-29). The CLI deliberately has no command for this (see
  ADR-0007);
- erase everything: delete the `~/.sensai` folder.

---

# [R1] RAG index

Detailed choices: [ADR-0009](../decisions/0009-rag-over-the-codebase.md).

## What is stored

| Data | Location | Content |
|---|---|---|
| Project index | M1 data folder (`~/.sensai/`, mode `700`) | **Copies of passages of the project** (code, documentation), their file and lines, and their embedding vector |

## Where this data goes

- Embeddings are computed by Ollama, on the machine set by `--host`. **With
  a remote server, the text of the whole indexed project goes to that
  server** during indexing, not only the useful passages.
- For each question, the passages judged relevant are added to the context
  sent to the model.

## Identified risks

| Risk | Planned situation | Limit |
|---|---|---|
| A secret of the project indexed then sent to the model | Hard-coded deny list (`.env*`, `*.pem`, `*.key`, `id_rsa*`…) applied even if `.gitignore` does not exclude them | A secret written in an ordinary code file is still indexed: that is the job of the Lot B guardrails ([EV2]) |
| Code of a confidential project sent to a remote server | Indexing follows `--host` | To be pointed out to the user; use a local Ollama for a confidential project |
| Copies of the code that persist after the project is deleted | The index stays in `~/.sensai/` | No purge of the index yet; deleting `~/.sensai` erases it |

---

# [X5] Scheduled tasks

Detailed choices: [ADR-0016](../decisions/0016-task-scheduling.md);
user guide: [scheduling.md](../architecture/scheduling.md).

## What is stored

| Data | Location | Content |
|---|---|---|
| Tasks | `~/.sensai/schedule/tasks.json` | The prompts written by the user, their intervals, the date and status of the last run |
| Run reports | `~/.sensai/schedule/runs/<task>/*.json` | **The model's answers**, the names of the tools called and their outcome (never their arguments), dates and errors |

The files stay on the machine. The last 50 reports of each task are kept,
older ones deleted at each new run. `sensai-schedule remove <task>` deletes
the task and all of `runs/<task>/`; deleting `~/.sensai/schedule/` erases
everything else. A task's prompt and what it reads go to the model as in an
interactive session: with a remote `--host`, they go to that server. An
answer may contain extracts of files read by a tool: do not schedule a task
on sensitive data with a remote model.

---

# [EV3] Turn journal

Detailed choices: [ADR-0053](../decisions/0053-server-side-turn-journal.md) (Proposed, 2026-11-01).

## What is stored

| Data | Location | Content |
|---|---|---|
| Turns | `~/.sensai/journal.db` (SQLite), table `turns` | Session id, project folder path, start date (UTC), time spent waiting for the model (ms), estimated tokens sent, outcome (answer, error, interrupted), interface (web or terminal) |
| Tool calls | same file, table `tool_calls` | Tool name, **arguments** (passed through the EV2 secret filter, then cut at 500 characters), duration, success, agent (main or sub-agent role) |

The arguments can contain file paths, search queries and the start of a file
the agent wrote: they are filtered for recognised secrets, but they are not
removed. No answer text and no tool result is stored.

## Where this data goes

Nowhere: the file stays on the machine. The web server reads it only for the
Journal page (`GET /api/journal`, `GET /api/journal/metrics`, token required).

## Identified risks

| Risk | Current situation | Possible fix |
|---|---|---|
| Another user of the machine reads the journal | Handled: file created in `600`, in the `700` data folder (same helpers as `sessions.db`) | A pre-existing folder keeps its permissions: `chmod 700 ~/.sensai` |
| Unlimited retention | Handled: turns older than `retention_days` (30 by default, same setting as sessions) are deleted at the start of `sensai` and `sensai-web` | `0` disables the purge |
| A deleted conversation stays in the journal | Handled for the web: `POST /api/sessions/{id}/delete` also deletes that session's journal rows, followed by a `VACUUM` | No delete command in the CLI; the retention purge covers it |
| An unrecognised secret in a tool argument | Stored (truncated) | Same limit as L3 in the [risk analysis](README.md); deleting `~/.sensai/journal.db` erases the journal |

---

# [M4] Project state document

Detailed choices: [ADR-0029](../decisions/0029-project-state-document.md).

## What is stored

| Data | Location | Content |
|---|---|---|
| State document | `SENSAI.md`, **in the project** | What is done, in progress, decisions and known problems, written by the user and by the agent (after confirmation) |
| Change log | `~/.sensai/state/<project fingerprint>.jsonl` | For each update: date, section, action, **old and new content of the section**, summary |

`SENSAI.md` is a project file: if it is committed, it is shared with
everyone who has access to the repository. Do not let the agent write
confidential information in it, or add it to `.gitignore`. Its content is
sent to the model with every message (system prompt, 8,000 characters at
most): with a remote `--host`, it goes to that server.

The log stays on the machine (folder `700`, file `600`). It keeps old
versions of sections, including text later removed from `SENSAI.md`: its
entries older than 30 days are deleted at start (`--retention-days`, same
rule as sessions), and deleting `~/.sensai/state/` erases it entirely.

---

# [M3] Structured fact memory

Detailed choices: [ADR-0030](../decisions/0030-structured-fact-memory.md).

## What is stored

| Data | Location | Content |
|---|---|---|
| Facts | `~/.sensai/memory.db`, table `facts` | Entity, attribute, value triples tied to the project path: versions, dependencies, **names of responsible people**, technical choices |
| History | `~/.sensai/memory.db`, table `fact_history` | Every creation, change and deletion, with old and new value and date |

A fact is saved only after the user confirms; the agent cannot delete any.
File readable by the user only (folder `700`, file `600`).

**No automatic purge**, unlike sessions: the memory is meant to last. The
names in the entity list and the facts looked up go to the model (system
prompt, `recall_facts` results): with a remote `--host`, they go to that
server.

Erase: `/facts forget <entity> [attribute] [value]` in the chat. An erased
fact stays in the history; to erase everything, history included, delete
`~/.sensai/memory.db`.

---

# [A6] Semantic answer cache

Detailed choices: [ADR-0033](../decisions/0033-conservative-semantic-cache.md).

## What is stored

| Data | Location | Content |
|---|---|---|
| Cached answers | `~/.sensai/cache.db`, table `answer_cache` | The question as typed, its embedding, the model's answer, the project path, the model, the date, the SHA-256 fingerprint of the files read and the number of times the answer was served |

File readable by the user only (folder `700`, file `600`). Never saved:
questions that depend on the conversation, and answers from a turn where the
agent wrote, executed, searched the web or looked up the fact memory. To
query the cache, only the question goes to the embedding server (the same as
for RAG); saved answers do not leave the machine.

An entry older than 30 days is removed when a question finds it; an entry no
question finds stays until `/cache clear`. Erase: `/cache clear` in the chat
(current project), or delete `~/.sensai/cache.db` (all projects).

---

# [X3] Share links (web interface)

Detailed choices: [ADR-0048](../decisions/0048-share-links.md).

## What is stored

| Data | Location | Content |
|---|---|---|
| Share links | `~/.sensai/shares.json` (`<data_dir>/shares.json`), mode `600` | For each link: the **SHA-256** of its token (never the token itself), a **snapshot of the conversation's user and assistant messages** passed through the EV2 output filter (recognised secrets masked), the session id, creation and expiry dates |

- A link expires after **7 days**. Expired links are removed from the file
  at server start (`sensai-web`); until then they are no longer served.
- Whoever has the link and can reach `sensai-web` reads the snapshot
  **without the access token**. The server listens on `127.0.0.1` by
  default, so in that setting only the same machine can open it.
- Revocation: `POST /api/shares/<token>/revoke` (with the access token).
  There is no button in the interface yet.
- The snapshot is a copy: **deleting the conversation does not delete its
  share links**. Revoke them, wait 7 days, or delete `shares.json`.

---

# [X1] Files attached in the web chat

- Attached text files (paperclip or drag and drop, at most 3 per message,
  text extensions only) are read **in the browser** and put in code blocks
  **inside the message**. Nothing is uploaded separately.
- They therefore follow the path of any message: the input filter masks
  recognised secrets, then the message goes to the model (to that server
  with a remote `--host`) and is **saved in `sessions.db`** with the
  session, with the same 30-day retention and the same deletion limit as
  above.
- A message over 20,000 characters is blocked before sending. PDF and docx
  are not accepted in the web.
