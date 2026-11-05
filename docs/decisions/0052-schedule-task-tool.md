# ADR-0052 — Scheduling (X5): the agent may propose a scheduled task, always on explicit approval

- **Status**: Accepted (2026-11-01, validated by the team)
- **Date**: 2026-11-01
- **Deciders**: Ridwane (Lot C) — to be confirmed by the team
- **Lot concerned**: B/X5 (`tools/schedule_task_tool.py`, scheduling), A (`tools/delegate_tool.py`, `core/agent.py`), D (`web/runtime.py`)

## Context

Tasks could only be scheduled with an explicit command (`sensai-schedule add`,
or `/schedule add` in the chat, [ADR-0028](0028-commandes-schedule-et-eval-dans-le-chat.md)).
Asking in plain language ("summarise the TODOs every morning") did nothing: the
agent had no tool for it, on purpose — what the model writes is never run as a
command. A scheduled task replays its prompt with nobody watching
([ADR-0016](0016-planification-des-taches.md)), so an instruction hidden in a
web page or a file the agent read could, through such a tool, plant an action that
runs every day: the worst case of prompt injection, because it persists.

Claude Code allows scheduling in plain language through tools gated by its
permission system, and runs the scheduled agents in an isolated cloud environment.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| Keep commands only (`/schedule add`) | No new risk | The user must know the syntax; the agent cannot help |
| **A `schedule_task` tool, always confirmed, not for sub-agents or scheduled tasks** (chosen) | Plain-language requests work; the user sees the exact prompt and frequency and decides; the existing unattended policy still applies at run time | One more write-level tool; relies on the user reading the confirmation |
| A tool that schedules without confirmation | Smooth | An injected instruction could create a recurring task: rejected |

## Decision

- New tool `schedule_task(id, prompt, every)`, risk `write`: the gateway always asks
  (a preference cannot loosen `write`, `tool_policy.LOOSENABLE`). The confirmation
  says the task will run **unattended** and shows the exact prompt and frequency.
- Registered in the CLI and the web server; never in `sensai-schedule` (which only
  loads `build_registry`) and never offered to a sub-agent
  (`delegate_tool.NEVER_DELEGATED`).
- The prompt is bounded (2,000 characters) and may not itself ask to schedule.
  The id is normalised to the scheduler's format (`resume_todo` → `resume-todo`).
- The task goes into the same `tasks.json`; `sensai-schedule loop` / `run-due` runs it
  with the unattended policy (risky actions refused).

## Consequences

- ✅ "Plan a daily summary of the TODOs" works from the CLI or the web, after one click.
- ✅ No new path for an injected instruction: nothing is saved without the user's yes,
  sub-agents and scheduled tasks cannot use the tool.
- ❌ The safety depends on the user reading the confirmation; a careless "yes" plants a
  recurring task (still limited by the unattended policy).
- ❌ The task runs only if `sensai-schedule loop` or cron runs; the agent says so, but
  nothing starts it automatically.
- ❌ Unlike Claude Code, tasks run on the user's machine, not in an isolated
  environment: the unattended policy is the only barrier.
- Follow-up: checked with `qwen3-coder:30b` on 2026-11-01, in the CLI and through
  `sensai-web`: task created after "yes", nothing created after "no" on the card, and
  the created task then run by `sensai-schedule run` (status ok). The same day, an empty `<tool_call>` tag the model left
  after its answer made the turn fail; `core/agent.py` now treats it as a final answer.
