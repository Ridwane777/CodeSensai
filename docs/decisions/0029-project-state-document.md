# ADR-0029 - Project state document: `SENSAI.md`, updated section by section

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-17
- **Deciders**: Ridwane (Workstream C)
- **Workstream**: C; A affected (`cli.py`: system prompt, `/state` command); B affected (a new tool goes through the gateway)

## Context
[M4] Artifact & State Document (issue #39, mandatory since ADR-0008):
the agent maintains a living document, distinct from the raw history (M1),
and must be able to **modify a specific section without rewriting the whole
document**, with an edit format our code can parse. DoD:
after several exchanges, the document reflects the project state without having been
corrupted or rewritten entirely. User stories:
[M4-state-document.md](../user-stories/M4-state-document.md).

Constraints:
- every write goes through the gateway (ADR-0006), and writing always
  requires a confirmation that no setting can remove (A3);
- the model context is shared between the history, RAG passages,
  tool results and their descriptions. Window configured on the validation
  pod: **32,768 tokens** (`OLLAMA_CONTEXT_LENGTH=32768`, pod setting,
  outside the repo);
- comparable tools store this kind of memory in a Markdown file
  in the project: per-agent instruction files, `memory-bank/` folder (Cline),
  `CONVENTIONS.md` (Aider). *Stated from memory, not re-verified on
  2026-10-17.*

## Considered options

**1. Where to store the document, and in what form**

| Option | Pros | Cons |
| --- | --- | --- |
| **A `SENSAI.md` file at the project root, `##` sections** (chosen) | Readable and editable by hand; versioned and shared with the project through Git; sections easy to split | One more file in the user's project (they can add it to `.gitignore`) |
| Several `.sensai/*.md` files, one per section | Impossible to damage a section by editing another | Heavier to read and load |
| In `~/.sensai`, outside the project | Does not touch the project | Invisible and not shared: contradicts US-M4-1 |

**2. Edit format**

| Option | Pros | Cons |
| --- | --- | --- |
| **Tool `update_state(section, action, content)`, `action` = `replace` or `append`** (chosen) | JSON arguments validated by the gateway; the code only touches the targeted section, the others stay byte-identical; the model never copies the document | One more tool |
| `diff`-format patch written by the model | Very general | Models often get lines and context wrong: patch rejected or applied in the wrong place |
| Full rewrite with `write_file` | Nothing to code | Excluded by the DoD: the model may forget or rephrase what the user wrote |

**3. Confirmation**

| Option | Pros | Cons |
| --- | --- | --- |
| **`write` risk: confirmation on every update, with the section before and after** (chosen) | Honest and consistent with A3 and ADR-0006, no exception to justify; the confirmation shows the diff | One confirmation per update; never any update in a scheduled task (X5 refuses writes) |
| Declare `read` to avoid confirmation | No interruption | Lying to the gateway: a prompt injection could make the agent write without the user seeing it |
| New "limited write" risk level | No interruption, honest | Changes Workstream B's policy and ADR-0006 for a single feature |

**4. What the agent knows at startup**

| Option | Pros | Cons |
| --- | --- | --- |
| **Content added to the system prompt, refreshed after each update, 8,000 characters at most** (chosen) | Known from the first message (US-M4-1), same mechanism as the M1 profile | Takes context on every turn (about 2,000 tokens at most, ~6% of 32,768) |
| On-demand reading through a tool | Costs nothing until used | Contradicts US-M4-1; the model forgets to read it |

**5. Trace and undo**

| Option | Pros | Cons |
| --- | --- | --- |
| **Local log `~/.sensai/state/<project>.jsonl` and commands `/state`, `/state history`, `/state undo <section>`** (chosen) | Covers US-M4-3 without an extra file in the project; per-section undo, without Git | Log not shared with the team |
| Git only | Nothing to code | Assumes a Git repo and a commit after every change; no per-section undo |
| Log inside the project | Shared | A file that grows in the project and keeps versions deleted on purpose |

## Decision
The state document is `SENSAI.md`, at the root of the folder where
`sensai` is launched, in Markdown, split by its `##` headings. On the first
update, if it does not exist, it is created with four sections: `Done`,
`In progress`, `Decisions`, `Known issues`. The user can add more
by hand; the agent cannot create any.

The agent edits it with the `update_state(section, action, content)` tool,
`write` risk:
- `replace` replaces a section's content, `append` adds text at
  its end;
- an unknown section is refused (with the list of existing sections),
  as is a `content` containing a heading line (`#` at the start of a line);
- the confirmation shows the section before and after;
- the write is atomic (temporary file then rename).

The content of `SENSAI.md` is added to the system prompt, framed as
data about the project and not as an instruction, truncated to 8,000
characters, and refreshed after each update. The prompt asks for an update
at the end of a task, not on every message. `SENSAI.md` is not
indexed by the RAG.

Every update is logged in `~/.sensai/state/<project>.jsonl`
(date, section, action, old and new content, summary), purged like
sessions (30 days). In the chat: `/state`, `/state history`,
`/state undo <section>`. Undo is reserved for the user, is itself
logged, and is refused if the section was edited by hand
since the agent's last update. Like Ctrl+Z, each
undo goes back one more change in the log: two
`/state undo` in a row undo the section's last two changes;
they do not cancel each other out. (First version: the second
undo reverted the first; changed after the trial run of 2026-10-17,
where that behavior proved confusing.)

## Consequences
- ✅ A human reads and corrects the document without a tool; the team shares it
  through Git with the code.
- ✅ Sections the agent does not target never change: the M4 DoD
  ("neither corrupted nor rewritten entirely") is guaranteed by the code, not by the
  model's goodwill.
- ✅ No exception to the gateway: the tool follows the same rules as
  `write_file`.
- ❌ A confirmation on every update: if the model updates too
  often, it gets tedious. To be measured during the trial run.
- ❌ In a scheduled task (X5), the document is never updated.
- ❌ The document costs up to about 2,000 tokens of context on every turn.
- ❌ The undo log is local: a teammate cannot undo a
  change made on another machine (they go through Git).
- ❌ The content of `SENSAI.md` can come from anyone in the repo:
  framing it as data limits the injection risk without removing it
  (same limit as EV4-OUT-14 for tool results).
- Follow-up: tests (sections byte-identical, refusals, atomic write,
  undo, truncation); trial run on the pod (several exchanges, then
  "where are we?" in a new session).
