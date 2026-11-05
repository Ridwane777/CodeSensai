# User stories — [X5] Scheduling

Command `sensai-schedule`, package `src/sensai/scheduling/`,
decision in [ADR-0016](../decisions/0016-planification-des-taches.md), how-to
in [scheduling.md](../architecture/scheduling.md). Tracking: issue #55.
Translated from French on 2026-10-29.

---

## US-X5-1 — Get a summary every day without starting anything by hand

**As** Camille, the developer who wants to know what changed in her project every morning,
**I want** to register a task "summarise today's log" that replays by itself every 24 h,
**so that** I find the agent's answer without opening a session or thinking about it.

**Acceptance criteria:**
- `sensai-schedule add resume --every 1d --prompt "…"` creates the task; `sensai-schedule list` shows it with its interval, last run, status and next due time.
- `sensai-schedule run-due`, started by cron or a systemd timer, runs the due tasks then stops; run again right after, it replays nothing.
- Each run leaves a JSON report (start, end, status, answer, tool calls) readable with `sensai-schedule history resume`.
- No confirmation is asked on screen during the run, and nothing is written to `sensai`'s session history.
- An interval under 60 seconds is refused; if the computer was off, the task does not catch up missed runs: it runs once at the next pass.

## US-X5-2 — Be sure an unattended task can neither write nor run code

**As** Marc, the lead who leaves the agent running at night,
**I want** a scheduled task to never be able to write a file or run code, even if a preference or content read by the model suggests it,
**so that** I do not depend on a confirmation nobody is there to give.

**Acceptance criteria:**
- A `write` or `execute` tool called during a scheduled task is not run: the agent gets a refusal, and the report records the call with the error `refused`.
- A preference `modes: {"mon_outil": "allow"}` changes nothing for these two risk levels.
- With `--tools lire,chercher` at creation, the other tools are not even offered to the model.
- After reading external content (file, web page), tools that are not read-only are refused for the rest of the run.
- The report only contains the names of the tools called and their outcome, never their arguments.

## US-X5-3 — A broken task blocks neither the others nor itself

**As** Marc, the lead who schedules several tasks for the team,
**I want** a task that crashes or exceeds its time limit not to prevent the next ones, and a task already running never to be started twice,
**so that** I do not discover after a week that everything stopped or that the model is saturated.

**Acceptance criteria:**
- If task A fails, task B of the same pass runs and has its own report; the command ends with code 1 to signal the failure.
- A time limit (600 s by default, `--timeout` to change it) and the agent's maximum number of steps bound each run; the report carries the status `timeout` or `max_iterations`.
- If a run of the same task is already in progress (lock file), the new pass skips it: status `skipped_locked`, the agent is not called and the last-run date does not move.
- A lock older than twice the task's time limit is considered abandoned (process killed) and taken over, with a warning.
- An unreadable `tasks.json` makes the command stop with code 2 and a message naming the file; the file is never modified.

## US-X5-4 — Schedule and check tasks without leaving the conversation

**As** Camille, the developer already working in the chat,
**I want** to type `/schedule add …`, `/schedule list` or `/schedule history …` in the conversation,
**so that** I manage my tasks without opening a second terminal.

**Acceptance criteria:**
- `/schedule list` shows the tasks of the session's data folder; a `/schedule …` line is neither sent to the model nor saved in the history.
- `/schedule loop` is refused with the explanation (it would freeze the chat); an unknown option or an unclosed quote shows the error and the chat goes on.
- A task created from the chat keeps X5's unattended policy: writing and running code refused.
- Written limit (ADR-0028): the output is shown on screen but does not enter the model's conversation.

> **Update on 2026-10-29:** ◐ Web interface ([ADR-0050](../decisions/0050-real-web-features-on-demand-evaluation.md), proposed): the Planning page lists, adds, pauses and removes the real tasks through `/api/schedule/tasks`, which read and write the same `<data_dir>/schedule/tasks.json` as `sensai-schedule`. The web server never runs a task: the page says to run `sensai-schedule loop` (or `run-due`). Tested (`tests/web/test_real_features.py`, `frontend/tests/realFeatures.test.tsx`), not yet with the real model.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): tasks were created, listed, paused and removed through the API and the Planning page, and a task created in the web was run by `sensai-schedule run-due` with its status visible in the web.

## US-X5-5 — Ask for a scheduled task in plain language
> **Status on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` in the CLI: "Planifie une tâche : chaque jour, résume les TODO du projet." → confirmation card, task `resume-todo` created after "y" and listed by `sensai-schedule list` ([ADR-0052](../decisions/0052-schedule-task-tool.md)).
> Refusal checked the same day: "Utilise schedule_task … bilan-tests" → card → "n" → the agent says it was refused, `bilan-tests` not created. Through `sensai-web`: `veille-web` created after approval (listed by `GET /api/schedule/tasks`), `nettoyage-web` refused and not created. Then `sensai-schedule run resume-todo` ran the task created in plain language: status ok, it summarised the project's `TODO.md`.

**As** Camille, the developer who does not remember the `/schedule add` syntax,
**I want** to ask the agent "summarise the TODOs every morning",
**so that** it proposes the task and I only have to approve it.

**Acceptance criteria:**
- The agent calls `schedule_task`; nothing is saved before I approve.
- The confirmation shows the exact prompt, the frequency, and that the task will run unattended.
- No preference can make it automatic; sub-agents and scheduled tasks cannot use it.
- After approval the task is in `sensai-schedule list` and the agent says it runs only while `sensai-schedule loop` (or cron) runs.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-X5-1 | ✅ | `scheduling/tasks.py`, `schedule_cli.py` | `tests/scheduling/test_tasks.py`, `tests/scheduling/test_schedule_cli.py` |  |
| US-X5-2 | ✅ | `scheduling/runner.py` | `tests/scheduling/test_unattended.py` (`write_and_execute_tools_are_refused_and_never_run`, `allow_preference_cannot_loosen_write_or_execute`) | The EV2 input filter is not applied to a task's prompt |
| US-X5-3 | ✅ | `scheduling/runner.py` | `tests/scheduling/test_runner.py` |  |
| US-X5-4 | ✅ | `web/server.py` (`/api/schedule`), `chat_commands.py` (`/schedule`) | `tests/test_chat_commands.py`, `tests/scheduling/test_schedule_cli.py` |  |
| US-X5-5 | ✅ | `tools/schedule_task_tool.py` | `tests/tools/test_schedule_task_tool.py` |  |
