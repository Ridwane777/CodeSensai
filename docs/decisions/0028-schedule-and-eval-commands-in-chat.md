# ADR-0028 - `/schedule` and `/eval` in the chat: reuse the existing commands

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Meric (Workstream B); pending team review
- **Workstream**: B (`chat_commands.py`); A (`cli.py` calls the module)

## Context
X5 (scheduling) and EV1 (evaluation) only exist as separate
commands (`sensai-schedule`, `sensai-eval`). That is their natural form
(cron calls `sensai-schedule run-due`, an evaluation is a script), but a
user who opens the chat does not see them: they cannot be demonstrated
"inside the agent". They need to be reachable from the conversation without
duplicating their logic.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| **`/schedule …` and `/eval …`: the line is split then passed to each command's `main`** | No duplicated logic, same options and exit codes, ~100 lines | Output goes to the screen, not into the conversation; a long command freezes the chat |
| Reimplement chat-specific subcommands | Controlled output, no dependency on argparse | Two implementations to keep aligned (X5 and EV1 are already tested) |
| Expose them as model **tools** | The model could schedule on its own | The model would create tasks running unattended: a prompt injection would become a persistent action. Contrary to ADR-0006 and ADR-0016 |
| Do nothing | No risk | X5 and EV1 invisible in a chat demo |

## Decision
Two commands, `/schedule` and `/eval`, typed by the user, delegated to the
existing `main` functions. The session supplies the data directory, the host and the
model (the session model acts as judge), unless the user provides the option
themselves. They are **not** tools: only the keyboard triggers them
(model text is never interpreted as a command). `/schedule
loop` is refused, because it never returns. A command line is sent
neither to the model nor to the history. An error (unclosed quote, unknown
option, crash) is displayed and the chat continues.

## Consequences
- ✅ X5 and EV1 can be demonstrated from the chat, with the tested behavior of the
  original commands; nothing to keep aligned.
- ✅ The model cannot schedule or evaluate on its own.
- ❌ The output of these commands does not enter the conversation: the model does not
  "know" a task was scheduled, and the history does not keep it.
- ❌ `/schedule run`, `/schedule run-due` and `/eval run` block the chat
  until they finish (a full judging run can take several minutes), with no
  progress bar and no clean cancellation other than Ctrl+C.
- ❌ argparse usage messages remain those of the original commands, not
  adapted to the chat (they mention `sensai-schedule`).
- ❌ A task created from the chat then runs unattended; it
  keeps the X5 policy (write and execution refused, ADR-0016), but its
  text is not checked by the input filter (ADR-0027): it is typed by the
  user.
- Follow-up: revisit whether the web interface (Workstream D) should offer the same commands
  (it would need captured output, not printed output); EV4 remains a
  `pytest` suite: a set of attack tests makes no sense in a conversation.
