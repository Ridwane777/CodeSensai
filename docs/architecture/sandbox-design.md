# Sandbox design: what it is, when the agent uses it, and why Docker

## 1. What the sandbox is

The goal of feature [T2] is to give the CodeSensai agent a safe place to run the code it writes. The agent cannot be trusted to write code that is harmless. It can contain bugs, infinite loops, or destructive commands. If that code ran on the host machine, it could delete files, read secrets, or hang the server.

The sandbox solves this: the code runs in a throw-away environment that is cut off from everything that matters. The agent gets back what happened (output, error, traceback) and can fix its own code.

```
user -> agent (Cerveau) -> writes code -> sandbox -> result (stdout / traceback)
                                ^                         |
                                +----- fixes and retries -+
```

## 2. Will the agent always use it?

Not automatically. The sandbox is a tool, not a wall around the whole agent. The agent uses it only when:

1. The agent (lot A, Cerveau) is connected to the MCP server (`sandbox-mcp`), which exposes the tool `execute_python`.
2. The agent decides to call that tool, guided by its system prompt and the tool description.

Nothing in this branch forces the agent to use it. Today the repo contains the sandbox, the MCP tool and a self-correction loop that works with a stub model, but no real agent yet.

To make "the user's code never runs outside the sandbox" actually true, the integration must also guarantee:

- **No other way to run code.** The agent must not have a raw shell or a direct `exec` tool. If one exists, the model can bypass the sandbox.
- **Confirmation before execution (A3).** The pre-execution hook is the place to require an explicit user "yes" before anything runs.
- **Secret filtering (EV2).** The same hook can mask API keys and other secrets in the code before it runs or is logged.

## 3. How it works with Docker

Each call to `run(code)` does the following:

1. Run the pre-execution hooks (A3 and EV2 will plug in here). If one refuses, stop and return a `Blocked` result. A hook that crashes also blocks.
2. Reject code larger than 100 KB.
3. Create a new container from `python:3.12-slim`, running `python -I -c <code>`. The code is passed as an argument, with no files shared with the host.
4. Start it and wait, with a timeout of 10 s by default and 60 s at most. On timeout, kill the container.
5. Read stdout and stderr separately, truncated to 64 KB each, and check whether the process was killed for memory.
6. Delete the container, always, even after an error.
7. Return a structured result: `ok`, `exit_code`, `stdout`, `stderr`, `traceback`, `error_type`, `error_message`, `timed_out`, `oom_killed`, `duration_s`, `truncated`.

Container restrictions:

| Restriction | Setting |
|---|---|
| Network | none (`network_mode=none`) |
| Filesystem | read-only, plus a 16 MB `/tmp` (`noexec`) |
| User | uid 65534 (non-root) |
| Privileges | all capabilities dropped, `no-new-privileges` |
| Memory | 256 MB (swap equal, so no swapping) |
| CPU | 0.5 CPU |
| Processes | 64 max |
| Host files | no volumes mounted |
| Cleanup | container labelled `codesensei.sandbox=1` and force-removed after each run |

If Docker is unavailable, `run` does not crash. It returns an error of type `SandboxError`, so the agent always receives something it can read.

## 4. The self-correction loop

`run_with_self_correction(task, model, sandbox, max_attempts=3)`:

1. The model returns code for the task.
2. The sandbox runs it.
3. If `ok` is true, stop.
4. Otherwise the model receives the previous result (error type, message, traceback) and returns a fixed version.
5. Repeat up to `max_attempts`.

The test proves this on real Docker: attempt 1 `print(undefined_var)` fails with `NameError`, attempt 2 prints `1`.

## 5. The alternative to Docker: an isolated subprocess

I proposed this option when we chose the stack, and recommended it if Docker could not be guaranteed on every machine. The code runs as a child process of the engine, restricted by the operating system instead of by a container:

- `subprocess` with `python -I` (isolated mode) and a cleaned environment (no inherited variables or secrets).
- A temporary working directory that is deleted afterwards.
- `resource.setrlimit` to cap memory (`RLIMIT_AS`), CPU time (`RLIMIT_CPU`), processes (`RLIMIT_NPROC`) and file size (`RLIMIT_FSIZE`).
- A hard timeout, killing the whole process group.

| | Docker (chosen) | Isolated subprocess |
|---|---|---|
| Network blocked | Yes, strictly | No, needs extra tools (namespaces, seccomp) |
| Files outside the sandbox | Not visible | Still readable if the OS user can read them |
| Resource limits | Memory, CPU, processes | Memory, CPU, processes via rlimit |
| Setup on each machine | Docker required | Only Python |
| Startup time | Slower (container creation) | Very fast |
| Strength of isolation | Strong | Weak: protects against accidents, not against a determined attacker |

We chose Docker because the T2 brief asks for "no network access and no files outside the sandbox", and a plain subprocess cannot guarantee either without extra work. The trade-off is that every machine that runs the demo needs Docker.

Stronger options exist (gVisor or Firecracker microVMs) but they are heavier to set up and were not needed for this project.

## 6. Limits to keep in mind

- Merged in #8: the code lives in `src/sensai/execution/sandbox/` and is described in [sandbox.md](sandbox.md). Its first version lived on the branch `feat/sandbox-execution` (see [sandbox-walkthrough.md](sandbox-walkthrough.md), kept for history).
- The self-correction loop is the agent's own loop (`core/agent.py`): the model reads the traceback returned by `run_code` and retries. Checked with `qwen3-coder:30b` on 2026-10-14 ([trial-2026-10-14.md](../performance/trials/trial-2026-10-14.md)).
- Code close to the 100 KB cap is not tested against the operating system's single-argument size limit (about 128 KB on Linux).
