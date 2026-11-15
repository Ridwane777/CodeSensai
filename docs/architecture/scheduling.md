# Task scheduling - [X5]

`sensai-schedule` replays agent tasks at a fixed interval, unattended.
Decision and trade-offs: [ADR-0016](../decisions/0016-task-scheduling.md).
User stories: [X5-scheduling.md](../user-stories/X5-scheduling.md).

The command is installed with the package (`pip install -e .`). It only uses
the standard library and the existing agent: no added dependency.

## How it works

1. You register tasks: an id, a prompt, an interval.
2. `sensai-schedule run-due` runs the due tasks **once**, then exits.
   cron (or a systemd timer) launches it regularly.
3. Each run leaves a JSON report.

A task is due if it has never run, or if the interval has elapsed since the
**start** of its last run. There is **no catch-up**: after three days of
downtime, a daily task runs once, not three times.

## Commands

Global options, placed before the command: `--data-dir`, `--model`, `--host`
(default: `config.json`, then `$SENSAI_HOME` / `~/.sensai` for the data).

| Command | Effect |
| --- | --- |
| `add ID --every 1d --prompt "…" [--tools a,b] [--timeout 600]` | Adds a task. `ID`: 1 to 40 characters from `a-z`, `0-9`, `-`. Interval: `30m`, `1h`, `1d`, `7d` or a number of seconds, **60 s minimum**. `--tools`: the only tools offered to the model (names checked against the registry); without it, all of them. |
| `list` | Id, interval, enabled or not, last run, status, next due time. |
| `remove ID` | Deletes the task **and** its reports (`runs/ID/`). |
| `enable ID` / `disable ID` | Re-enables / suspends a task without deleting it. |
| `run-due [--dry-run]` | Runs the due tasks. `--dry-run` lists them without running or writing anything. |
| `run ID` | Runs a task now, due or not (the lock is still respected). |
| `history ID [-n 10]` | Latest reports, newest first. |
| `loop [--every 300]` | Calls `run-due` every N seconds (minimum 60) until Ctrl+C. Fallback mode without cron or systemd. |

Exit codes: `0` all good (tasks `ok` or skipped), `1` a task
failed (`error`, `timeout`, `max_iterations`) or a requested task does not
exist, `2` misuse or unusable task file.

The shared registry (`src/sensai/registry.py`) offers `run_code`,
`read_file`, `write_file` and `web_search`. Unattended, only reading
and web search go through: `run_code` and `write_file` require
confirmation, so they are always refused (ADR-0016). The EV2 guardrails
mask secrets in what the tools return.

## Hooking up cron

```cron
# Every 15 minutes: run what is due (each task's interval decides the rest).
*/15 * * * * SENSAI_HOME=/home/moi/.sensai /home/moi/sensai/.venv/bin/sensai-schedule run-due >> /home/moi/.sensai/schedule/cron.log 2>&1
```

- Use the command's **full path**: cron does not have a terminal's `PATH`.
- cron does not read your profile: set `SENSAI_HOME` in the line (or
  `data_dir` in `config.json`) if the data is not in `~/.sensai`.
- `config.json` and `prompts/` are looked up in the current folder, then in
  the repository; cron's current folder is `$HOME`.
- Warnings (stale lock taken over, unreadable report) go to
  stderr, hence the redirection.

## Hooking up a systemd timer (user)

`~/.config/systemd/user/sensai-schedule.service`

```ini
[Unit]
Description=CodeSensai scheduled tasks

[Service]
Type=oneshot
Environment=SENSAI_HOME=/home/moi/.sensai
ExecStart=/home/moi/sensai/.venv/bin/sensai-schedule run-due
```

`~/.config/systemd/user/sensai-schedule.timer`

```ini
[Unit]
Description=Runs due CodeSensai tasks every 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=false

[Install]
WantedBy=timers.target
```

Then `systemctl --user daemon-reload && systemctl --user enable --now sensai-schedule.timer`.
Output goes to `journalctl --user -u sensai-schedule.service`. These two
examples must be adapted; the command itself is tested in `tests/scheduling/`.

## Where the files are

Under `<data>/schedule/` (`~/.sensai/schedule/` by default), a folder created with mode `700` if it did not exist:

| File | Content |
| --- | --- |
| `tasks.json` | Task list: `id`, `prompt`, `interval_s`, `enabled`, `created_at`, `last_run_at`, `last_status`, `timeout_s`, and `tools` if a list was given. Atomic write; if it is unreadable or malformed, the command stops (code 2) naming the file, **without rewriting it**. |
| `runs/<id>/<UTC timestamp>.json` | One report per run. The last 50 per task are kept, older ones are deleted. |
| `locks/<id>.lock` | Lock present while a run is in progress (`pid`, `started_at`). |

### Run report

```json
{
  "task_id": "resume",
  "started_at": "2026-10-14T08:00:00+00:00",
  "finished_at": "2026-10-14T08:00:12+00:00",
  "status": "ok",
  "answer": "text of the final answer",
  "tool_calls": [{"name": "lire", "ok": true}, {"name": "ecrire", "ok": false, "error": "refused"}],
  "error": null
}
```

Statuses: `ok`, `error` (agent unreachable, crash, reported error),
`max_iterations` (6 model calls without a final answer), `timeout`,
`skipped_locked` (another run of the same task was in progress).
`tool_calls` holds the **name** and outcome of each tool (`ok`, or the gateway
error code), never the arguments. The model's answer, however,
is stored as is.

## Unattended policy

- Each run uses a fresh tool gateway with the `deny_all`
  confirmer: **a tool that requires confirmation is always refused**. By
  default, that is every `write` or `execute` tool. No preference
  can relax this for those two levels.
- Preferences come from the `tools` key of `config.json` if it exists
  (the interactive CLI reads it too). `confirm_after_untrusted` is
  forced to `true`: after a read or network tool has answered, no
  tool other than a read tool goes out.
- The model is told that nobody can confirm and that it must not
  retry a refused tool.
- No history: each run starts from the system prompt and the task
  prompt, and nothing is written to `sessions.db`.

## Limitations

- **No task that writes or runs code**, by design.
- A task can still send a request through a network tool as long as no
  tool has answered in the run: give each task the shortest possible
  `--tools` list. See ADR-0016.
- The timeout (`--timeout`, 600 s by default) is only checked **between two
  agent events**. A model call that does not answer cannot be
  interrupted from the loop: the command waits. Tool calls have
  their own timeout in the gateway (120 s by default).
- A lock older than **twice** the task timeout is considered
  left by a killed process: it is removed (with a warning) and
  the run proceeds. Two passes taking over the same stale lock at the same
  instant can overlap.
- No cron expressions, no time zone: stored dates are in UTC;
  `list` shows the next due time in local time.
- Editing `tasks.json` while a pass is running can lose one of the two
  edits (no transaction).
