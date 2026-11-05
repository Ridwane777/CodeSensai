# Sandbox walkthrough: every file, explained line by line

> **Historical document.** It explains the first version of the sandbox, on the
> branch `feat/sandbox-execution` (`src/sandbox/…`), which was not merged as is.
> The code in `main` lives in `src/sensai/execution/sandbox/` and is described in
> [sandbox.md](sandbox.md). File names and line numbers below do not match `main`.

Branch: `feat/sandbox-execution`. Line numbers match the files as committed. Consecutive lines that do one job are grouped into a range (for example `5-9`) so the page stays readable.

How the pieces fit together:

```
correction_loop.py --calls--> executor.py (DockerSandbox.run) --uses--> config.py, result.py
mcp_server.py      --calls--> executor.py
tests/*            --exercise--> all of the above
```

---

## `pyproject.toml` (project definition)

| Lines | What it does |
|---|---|
| 1-3 | Uses `hatchling` to build the package. |
| 5-9 | Project name `codesensei-sandbox`, version 0.1.0, Python 3.12 or newer. |
| 10-13 | Runtime dependencies: `docker` (talks to the Docker daemon) and `mcp` (the MCP server). `mcp` is capped below 2 because version 2 renamed `FastMCP`, which this code imports. |
| 15-16 | Optional `dev` extra that installs `pytest`. |
| 18-19 | Creates the command `sandbox-mcp`, which runs `sandbox.mcp_server:main`. |
| 21-22 | Tells hatchling the package lives in `src/sandbox`. |
| 24-29 | pytest setup: tests are in `tests/`, `src/` is put on the import path, and the `docker` marker is registered so pytest knows it. |

## `.gitignore`

Ignores the virtual environment (`.venv/`), Python caches (`__pycache__/`, `*.py[cod]`, `.pytest_cache/`) and build output (`*.egg-info/`, `dist/`, `build/`).

## `src/sandbox/__init__.py`

Empty. It only marks `sandbox` as a Python package.

---

## `src/sandbox/config.py` (limits)

| Lines | What it does |
|---|---|
| 1 | Module docstring. |
| 3 | Makes type annotations lazy, so `float \| None` works cleanly. |
| 5 | Imports `dataclass`. |
| 7-8 | Label `codesensei.sandbox=1` put on every container. The tests and a cleanup check use it to find containers that were left behind. |
| 11-12 | `SandboxConfig` is a frozen (read-only) dataclass, so limits cannot change after creation. |
| 13 | Docker image: `python:3.12-slim`. |
| 14-15 | Default timeout 10 s, hard maximum 60 s. |
| 16 | Maximum code size: 100 KB. |
| 17 | Maximum captured output per stream: 64 KB. |
| 18 | Memory limit 256 MB. |
| 19 | CPU limit, 500 000 000 nano-CPUs, which is half a CPU. |
| 20 | At most 64 processes. |
| 21 | Run as user and group 65534 (`nobody`), not root. |
| 22-23 | Working directory `/tmp`, and the size of that tmpfs (16 MB). |
| 25-26 | `clamp_timeout` turns whatever the caller asked for into a safe timeout. |
| 27-28 | No timeout given: use the default. |
| 29-32 | Try to read it as a number. If that fails, use the default. |
| 33-34 | NaN (`value != value`) or zero or negative: use the default. |
| 35 | Otherwise use the value, capped at 60 s. |

## `src/sandbox/result.py` (what the agent gets back)

| Lines | What it does |
|---|---|
| 7 | The text Python prints at the start of every traceback. |
| 10-15 | `extract_traceback` finds the last occurrence of that text in stderr and returns everything from there on, or `None` if there is none. Taking the last one matters when exceptions are chained. |
| 18-23 | `parse_error` reads the error name and message from the last line of a traceback. It returns `(None, None)` if there is no traceback. |
| 25-27 | If the last line is indented, it is not an exception line, so there is no usable error. |
| 28-31 | Splits on the first `:` into name and message. A name that is empty or contains a space is not an exception name. |
| 32 | Returns the name without its module (`package.errors.CustomError` becomes `CustomError`) and the message. A bare name such as `KeyboardInterrupt` gets an empty message. |
| 35-36 | `ExecutionResult` is a dataclass. |
| 37-38 | `ok` (success flag) and `exit_code` (process exit code, `None` if it never ran or was killed). |
| 39-41 | `stdout`, `stderr` and the extracted `traceback`. |
| 42-43 | `error_type` and `error_message`, for example `NameError` and `name 'x' is not defined`. |
| 44-45 | `timed_out` and `oom_killed` flags. |
| 46-47 | `duration_s` and `truncated` (output was cut). |
| 49-50 | `to_dict` converts the result to a plain dict, which is what MCP returns. |
| 52-63 | `failure` builds a result for problems outside the user's program (Docker missing, code too big, blocked by a hook): `ok=False`, no exit code, an error type and message. |

## `src/sandbox/executor.py` (the core)

| Lines | What it does |
|---|---|
| 1-3 | Docstring and lazy annotations. |
| 5-13 | Imports: logging, time, typing helpers, `docker`, `requests` (the Docker library raises its errors), and Docker's own exceptions. |
| 15-16 | Imports the config values and the result helpers. |
| 18 | Module logger. |
| 20-21 | Docker log settings: a 4 MB file, one file. Without this, a program that prints without end could fill the host disk. |
| 24-34 | `HookDecision`: the answer a pre-execution hook gives. `allowed=False` stops the run, `reason` explains why, and `code` (if set) replaces the code that will run, so a hook can mask secrets. |
| 37 | `PreExecutionHook`: any function that takes the code and returns a `HookDecision`. This is the plug-in point for A3 and EV2. |
| 40-44 | `DockerSandbox` class. Its docstring promises `run` never raises. |
| 46-56 | Constructor: uses the given config or the default, keeps an optional Docker client (tests inject fakes here), and copies the hooks list. |
| 60 | `run(code, timeout_s)` is the main entry point. |
| 62-63 | If `code` is not a string, return a `SandboxError` instead of crashing. |
| 64-66 | Run the hooks. If one blocks, return its `Blocked` result immediately, before any container exists. |
| 67-70 | Reject code over 100 KB (measured in bytes, not characters). |
| 71 | Turn the requested timeout into a safe one. |
| 73-74 | Start a clock. `container = None` so cleanup is safe if creation fails. |
| 75-80 | Get the Docker client, make sure the image exists, create the container with the hardened settings, restart the clock, and start it. |
| 81-82 | Wait for it to finish (or time out) and measure the duration. |
| 83-84 | Read stdout and stderr separately. |
| 85 | Check whether the container was killed for running out of memory. |
| 86-92 | If Docker itself fails (daemon down, network error, OS error), log it and return a `SandboxError` result. |
| 93-94 | `finally`: always delete the container, whatever happened above. |
| 96-98 | Turn the raw pieces into an `ExecutionResult`. |
| 102-106 | `_apply_hooks` docstring. It fails closed. |
| 107-108 | For each hook, work out a name for error messages. |
| 109-114 | Call the hook. If it raises an exception, block the run. |
| 115-118 | If the hook returned something that is not a `HookDecision`, block the run. |
| 119-122 | If the hook said no, block the run with its reason. |
| 123-124 | If the hook gave replacement code, use it for the next hooks and for execution. |
| 125 | All hooks passed: return the (possibly rewritten) code and no block. |
| 127-132 | `_get_client` connects to Docker the first time and pings it so a dead daemon fails immediately. The client is kept for later calls. |
| 134-138 | `_ensure_image` pulls the image only if it is not already local. |
| 140-161 | `_container_kwargs` holds every setting of the container: |
| 143-144 | the image, and the command `python -I -c <code>` (`-I` is isolated mode: ignores environment variables and the current directory). |
| 145 | the cleanup label. |
| 146 | two Python environment variables: no `.pyc` files, and unbuffered output. |
| 147-148 | working directory and non-root user. |
| 149-150 | network off, set twice (`network_disabled` and `network_mode="none"`) for safety. |
| 151-152 | read-only root filesystem, with a small writable `/tmp` that cannot run programs (`noexec`) or use setuid (`nosuid`). |
| 153-154 | memory limit, and swap set to the same value so it cannot swap past it. |
| 155-156 | CPU and process limits. |
| 157-158 | drop every Linux capability and forbid gaining new privileges. |
| 159-160 | the log cap, and `auto_remove=False` because the code removes the container itself after reading its logs and exit state. |
| 163-177 | `_wait`: waits up to `timeout` seconds. |
| 167-168 | Normal finish: returns "did not time out" and the exit code. |
| 169-172 | The Docker library signals a timeout with a `ReadTimeout` or `ConnectionError`. |
| 173-176 | Kill the container. If it just finished by itself, ignore that error. |
| 177 | Return "timed out" and no exit code. |
| 179-182 | `_oom_killed` refreshes the container state and reads Docker's `OOMKilled` flag. |
| 184-191 | `_remove` force-deletes the container. If that fails it only logs a warning, so cleanup never hides the real result. |
| 193-201 | `_build_result` receives the raw outputs and flags. |
| 202-204 | Output cap, and whether each stream was longer than it. |
| 205 | Keep the first 64 KB of stdout, decoded as UTF-8 (bad bytes replaced). |
| 206-207 | Keep the last 64 KB of stderr, because the traceback is at the end. |
| 209-210 | Extract the traceback and parse the error type and message. |
| 211-213 | Timed out: the error type becomes `Timeout`. |
| 214-216 | Out of memory: the error type becomes `OOMKilled`. |
| 217-218 | Non-zero exit with no Python traceback (for example exit 137): the message says which exit code. |
| 220-232 | Build the result. `ok` is true only for exit code 0 with no timeout and no memory kill. Duration is rounded to milliseconds. |

## `src/sandbox/mcp_server.py` (the tool the agent calls)

| Lines | What it does |
|---|---|
| 5-9 | Imports `asyncio`, `FastMCP` and `DockerSandbox`. |
| 12-14 | `create_server` builds the server. Tests pass a fake sandbox, otherwise a real one is created. |
| 15 | Creates the MCP server named `codesensei-sandbox`. |
| 17-18 | Registers the tool `execute_python(code, timeout_s=10)`. It is `async` so a run of up to 60 s does not freeze the server. |
| 19-29 | The docstring becomes the tool description the model reads. It lists the returned fields, tells the model to fix the code and call again when `ok` is false, and states the limits. |
| 30 | Runs the blocking Docker call in a worker thread. |
| 31 | Returns the result as a dict. |
| 33 | Returns the server. |
| 36-37 | `main` starts the server over stdio, which is how an agent connects to a local MCP server. |
| 40-41 | Lets you run it with `python -m sandbox.mcp_server`. |

## `src/sandbox/correction_loop.py` (self-correction)

| Lines | What it does |
|---|---|
| 1-6 | Docstring: the model is any function taking the task and the last result and returning code. |
| 10-15 | Imports. |
| 17 | `ModelFn` type: `(task, last_result) -> code`. |
| 20-21 | `_Runner` describes anything with a `run` method, so tests can use a fake sandbox. |
| 24-28 | `LoopOutcome`: whether it succeeded, every attempt as `(code, result)`, and the last code. |
| 31-42 | `format_feedback` turns a failed result into text for a prompt. |
| 33-34 | If it succeeded, say so. |
| 35-37 | Start with "The code failed with `<error type>`", plus the message. |
| 38-41 | Add the traceback, or stderr if there is none. |
| 42 | Join into one string. |
| 45-50 | `run_with_self_correction(task, model, sandbox, max_attempts=3)`. |
| 52-53 | Refuses `max_attempts` below 1. |
| 54-55 | Starts with an unsuccessful outcome and no previous result. |
| 56-58 | Each round: ask the model for code (it sees the last result), then run it in the sandbox. |
| 59-60 | Record the attempt and the code. |
| 61-63 | If it ran cleanly, mark success and stop. |
| 64 | Return the outcome, success or not, after the last attempt. |
| 67-77 | `StubModel`: a fake model that returns a fixed list of code attempts and records what it was called with. It stays on the last attempt if it runs out. Used for the demo and the tests. |
| 80-90 | `_demo` runs the buggy-then-fixed scenario against real Docker and prints each attempt. |
| 93-94 | Lets you run it with `python -m sandbox.correction_loop`. |

---

## Tests

### `tests/conftest.py` (shared setup)

| Lines | What it does |
|---|---|
| 7-16 | `_docker_client` tries to connect to Docker and returns `None` if it cannot. |
| 19-24 | Session fixture `docker_client`: skips the test if Docker is not reachable. This is why tests are skipped, not failed, without Docker. |
| 27-37 | Session fixture `sandbox_image`: pulls the image once, so the first download never counts against a test timeout. |
| 40-42 | Session fixture `sandbox`: one shared `DockerSandbox` for the Docker tests. |
| 45-49 | For every test marked `docker`, adds the image fixture automatically. |
| 52-63 | Automatic fixture that runs after each Docker test and fails the test if any container with the sandbox label still exists. |

### `tests/test_executor.py`

| Lines | Test | What it checks |
|---|---|---|
| 9-13 | (constant) | A sample `NameError` traceback. |
| 16-19 | `test_extract_traceback_and_parse_error` | Extraction ignores text before the traceback, and the error is parsed as `NameError`. |
| 22-24 | `test_extract_traceback_none_without_marker` | No traceback gives `None`. |
| 27-36 | `test_parse_error_uses_last_traceback_and_strips_module` | With two tracebacks, the last wins, the module path is removed, and a colon in the message is kept. |
| 39-41 | `test_parse_error_bare_exception_name` | `KeyboardInterrupt` with no message gives an empty message. |
| 44-51 | `_NoDocker` | A fake client that fails the test if anything touches containers or images. |
| 54-67 | `test_denying_hook_blocks_without_container` | A refusing hook gives `Blocked`, receives the code, and no container is created. |
| 70-75 | `test_raising_hook_fails_closed` | A hook that crashes also blocks. |
| 78-81 | `test_oversized_code_rejected_without_container` | Code over 100 KB gives `SandboxError`, no container. |
| 84-93 | `test_unreachable_docker_returns_sandbox_error` | If connecting to Docker raises, the result is `SandboxError`, not a crash. |
| 96-103 | `test_timeout_is_clamped` | None gives 10, 1000 gives 60, -1 gives 10, 2 stays 2. |
| 109-115 | `test_hello_world` | Real run: output `hello world`, no error, no flags. |
| 118-127 | `test_name_error_is_structured` | `print(undefined_var)` gives exit code 1, `NameError`, a traceback, and the dict form. |
| 130-136 | `test_stdout_and_stderr_are_separate` | The two streams do not mix. |
| 139-145 | `test_infinite_loop_times_out` | `while True: pass` with a 2 s timeout is killed and reported as `Timeout`. |
| 148-152 | `test_output_is_truncated` | 200 000 characters of output are cut to 64 KB and flagged. |
| 155-159 | `test_allowing_hook_can_rewrite_code` | A hook can replace the code, and the replacement is what runs. |

### `tests/test_security.py` (all marked `docker`)

| Lines | Test | What it checks |
|---|---|---|
| 9 | (constant) | Path of the repository on the host. |
| 12-22 | `test_no_network` | Connecting to `1.1.1.1:53` fails. |
| 25-36 | `test_root_filesystem_is_read_only` | Writing to `/etc/x`, `/x`, `/usr/x` is denied three times. |
| 39-49 | `test_runs_as_unprivileged_user_without_capabilities` | The user is 65534:65534 and the effective capability mask is zero. |
| 52-59 | `test_tmp_is_writable` | `/tmp` can be written and read, so normal scripts can work. |
| 62-67 | `test_memory_limit_is_enforced` | Allocating 512 MB against 256 MB fails. The assertion accepts an OOM flag, exit code 137 or `MemoryError`, because Docker reports it in different ways. |
| 70-86 | `test_process_limit_is_enforced` | Starting 200 processes fails before the end, and the test kills any it did start. |
| 89-97 | `test_host_files_are_not_visible` | The repo path and `pyproject.toml` do not exist inside, `/home` is empty, and the Docker socket is absent. |

### `tests/test_mcp_tool.py`

| Lines | Test | What it checks |
|---|---|---|
| 15-21 | `FakeSandbox` | Records calls and always returns success. |
| 24-30 | `test_tool_is_registered_with_guidance` | The server has exactly one tool, `execute_python`, whose description mentions fixing, with inputs `code` and `timeout_s`. |
| 33-43 | `test_tool_returns_result_dict` | Calling the tool passes the code and timeout to the sandbox, and the reply has the same fields as `ExecutionResult`. |
| 46-58 | `_list_tools_over_stdio` | Starts the server as a separate process and talks to it like a real MCP client. |
| 61-64 | `test_stdio_server_lists_execute_python` | Through that real connection, the only tool is `execute_python`. |
| 67-74 | `test_tool_runs_real_code` | With real Docker, a buggy script comes back as `ok=False` with `NameError`. |

### `tests/test_correction_loop.py`

| Lines | Test | What it checks |
|---|---|---|
| 14-21 | `ScriptedSandbox` | Returns prepared results in order. |
| 24-32 | `_fail` | Builds a failed `NameError` result. |
| 35-42 | `test_loop_fixes_code_with_fake_sandbox` | Fail then succeed: success, final code is the fix, and the model saw no result first, then the `NameError`. |
| 45-49 | `test_loop_gives_up_after_max_attempts` | Two failures with `max_attempts=2`: not successful, two attempts. |
| 52-55 | `test_loop_stops_on_first_success` | Success on the first try: one attempt only. |
| 58-60 | `test_invalid_max_attempts` | Zero attempts raises `ValueError`. |
| 63-65 | `test_format_feedback_includes_traceback` | The feedback text contains the error name and the traceback. |
| 68-81 | `test_definition_of_done_buggy_then_fixed_against_real_docker` | The Definition of Done on real Docker: attempt 1 fails with `NameError`, attempt 2 prints `1`, and the model received the first error when asked for the fix. |

---

## `docs/architecture/sandbox.md` and `docs/architecture/sandbox-design.md`

`docs/architecture/sandbox.md` (committed, 105 lines) is the usage note: how to run the sandbox, the limits, the hook seam and the MCP server. This page does not annotate it line by line. `docs/architecture/sandbox-design.md` explains the design and the Docker versus subprocess choice.

---

## Things to know when reading the code

- `executor.py:169-172` treats any `ConnectionError` as a timeout. A real Docker connection failure during `wait` would be reported as `Timeout` instead of `SandboxError`.
- `test_memory_limit_is_enforced` accepts three different outcomes, so it is a weaker check than the others.
- The code goes to the container as a command-line argument. Code near the 100 KB cap has no test against the operating system's single-argument size limit (about 128 KB on Linux).
