# ADR-0016 — Scheduling: `sensai-schedule run-due` called by cron, no daemon or dependency

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Meric (Workstream B); to be approved by the team
- **Workstream**: B (tool gateway, unattended policy); A (agent loop reused as is)

## Context
Feature X5 asks to replay agent tasks at a fixed interval (issue #55).
Nobody is in front of the screen at that moment, and that changes
everything: the tool gateway (ADR-0006) protects risky actions with a
**user confirmation** (A3), yet here there is nobody to answer. A failing
task must also not block the others, the same task must not run twice at
the same time, and it must be possible to review what happened.
Constraints: no new dependency, project used on developer laptops (Linux,
sometimes WSL or macOS).

## Considered options
### Scheduler
| Option | Pros | Cons |
| --- | --- | --- |
| APScheduler (library) | Cron, intervals, persistence, very common | New major dependency (to document, to keep up to date), a process that must stay alive, lots of features useless here |
| cron / systemd alone, without a dedicated command | Nothing to write | One command per task would have to be written by hand; no guarantee of non-overlap, reporting or unattended policy |
| Daemon: a scheduling thread inside `sensai` | No system configuration | Tasks only run while the interactive session is open; a thread calling the agent and the gateway in parallel with the conversation shares its state (e.g. "untrusted content read") |
| **`run-due` command (one pass then exit) called by cron/systemd, stdlib only** — chosen | The operating system already knows how to relaunch, log and survive reboots; testable with an injected clock; zero dependencies | The user must write a crontab line or a timer; `loop` is only a fallback mode |

### Task storage
| Option | Pros | Cons |
| --- | --- | --- |
| **A JSON file** — chosen | Readable and fixable by hand, a few tasks per user, atomic write (temporary file then `os.replace`) | No transaction: two processes writing at the same time can lose a change |
| SQLite (like sessions, ADR-0007) | Transactions, concurrent access | Disproportionate for a dozen rows; less readable; a damaged file is harder to repair by hand |

## Decision
Tasks (prompt + interval in seconds, 60 s minimum) are stored in
`<data>/schedule/tasks.json`. The `sensai-schedule run-due` command runs
the due tasks once then stops; cron or a systemd timer triggers it. It
relies on the standard library only.

**Unattended policy.** Each run receives a fresh `ToolGateway` whose
confirmer is `deny_all`, passed explicitly. Consequences:
- a tool whose mode is "ask" (`write` and `execute` by default) is
  **always refused**; the model receives the refusal as an observation;
- preferences cannot relax `write` or `execute`
  (`tool_policy.LOOSENABLE`), so an `allow` line in `config.json` changes
  nothing here either;
- `confirm_after_untrusted` is forced: after reading external content, no
  tool other than read-only ones can run;
- a per-task `--tools` list removes the other tools from what the model
  sees;
- the system prompt is preceded by a note: unattended run, do not retry a
  refused tool, say what could not be done.

**Isolation.** Each task is in its own `try/except`: a crash gives the
`error` status and the next task starts. A lock file (`O_CREAT|O_EXCL`)
prevents two simultaneous runs; a lock older than twice the task's timeout
is considered abandoned and taken over. The timeout (600 s by default) is
checked between two agent events, and the number of steps is bounded by
`MAX_ITERATIONS`.

**Intervals only, no cron expressions**, and no catch-up of missed runs: a
due task runs once, not ten times.

## Prompt injection risk
Content read during a task (web page, file) may contain instructions aimed
at the model. What the decision **limits**: it can neither write nor
execute (refusal), and as soon as a read or network tool has answered,
`confirm_after_untrusted` turns any subsequent call of a tool that is not
read-only (so `network` too) into a confirmation request, which `deny_all`
refuses. What it **does not solve**: `network` tools remain allowed
unattended as long as no tool has answered yet in the run, and a read tool
always remains callable. A first network call may therefore go out with
what the model already had in mind (the task prompt, the system prompt),
and a search query is a URL that goes out to the engine: data could leak
through that channel. Mitigations: the `--tools` list (give a task only what
it needs), `deny_all`, `confirm_after_untrusted`, and the EV2 guardrails —
these still need wiring, since neither the interactive CLI nor the
scheduler passes any to the gateway in `main` today. We do not claim
injection is impossible.

## Consequences
- ✅ Zero dependencies added; no process to monitor; everything is testable without Ollama or a real clock.
- ✅ A guarantee that is simple to explain: unattended, nothing that writes or executes happens.
- ✅ One report per run (50 kept per task), without tool arguments.
- ❌ **No writing or executing task is possible** (e.g. "fix the typos in this file every night"): that is the price of safety; it would take a deferred-confirmation mode (queue of actions to approve) in a new ADR.
- ❌ No catch-up: if the machine is off, missed runs are lost.
- ❌ No cron expressions ("every Monday at 9 am"): only "every N minutes/hours/days"; an expression can at a pinch be expressed via cron's own schedule.
- ❌ The user must install the cron line or the systemd timer themselves (examples in [scheduling.md](../architecture/scheduling.md)).
- ❌ The JSON file is not transactional: the write is atomic, but two processes modifying tasks at the same time (e.g. `add` while a pass finishes) can lose a change. The scheduler rereads the file before each update to shrink the window, without eliminating it.
- ❌ The timeout cannot interrupt a blocking call (model not answering, tool stuck): it is only checked between two events. No forced stop is promised; tool calls have their own timeout in the gateway, and the stale lock eventually frees the task.
- ❌ Taking over a stale lock is time-based: two passes taking over the same lock at the same instant can overlap.
- Follow-up: tests in `tests/scheduling/`. To revisit if tasks become numerous or shared between users (switch to SQLite), if precise schedules are wanted (cron expressions, or APScheduler) or if a deferred-confirmation mode is requested.
