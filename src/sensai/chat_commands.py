"""
Chat commands `/schedule` and `/eval` - features [X5] and [EV1], ADR-0028.

These are the same commands as `sensai-schedule` and `sensai-eval`, typed without
leaving the conversation. The module reimplements nothing: it splits the line,
adds the session's data directory, host and model, then calls each tool's
`main`. One source of truth for options and exit codes.

Only a line typed by the user reaches this module (the CLI loop reads the
keyboard); what the model writes is never interpreted as a command.
"""
from __future__ import annotations

import shlex
from collections.abc import Callable, Sequence

from sensai.eval.cli import main as eval_main
from sensai.schedule_cli import main as schedule_main

COMMANDS = ("/schedule", "/eval")

USAGE = {
    "/schedule": (
        "Usage: /schedule add <id> --every 1d --prompt \"…\" | list | run <id> | run-due"
        " | history <id> | enable|disable|remove <id>"
    ),
    "/eval": (
        "Usage: /eval run --dataset <file.jsonl> --out <report.json>"
        " | compare <report_a> <report_b>"
    ),
}

# `loop` never returns: it would freeze the chat. Run it in another terminal.
_FORBIDDEN = {"/schedule": {"loop"}}


def is_chat_command(line: str) -> bool:
    """True if the line *starts* with one of these commands.

    "why does /eval fail?" is a question for the model, not a command.
    """
    parts = line.split(None, 1)
    return bool(parts) and parts[0] in COMMANDS


def _with_default(argv: list[str], flag: str, value: str | None) -> list[str]:
    """Prepend `flag value` unless the user passed it already."""
    if value and flag not in argv:
        return [flag, value, *argv]
    return argv


def run_chat_command(
    line: str,
    *,
    host: str,
    model: str,
    data_dir: str | None,
    output_fn: Callable[[str], None] = print,
    schedule: Callable[[Sequence[str]], int] = schedule_main,
    evaluate: Callable[[Sequence[str]], int] = eval_main,
) -> int:
    """Run the line and return the exit code (0 = success).

    Never raises: a malformed argument or a failure is printed and the
    conversation goes on. `schedule` and `evaluate` are injectable for tests.
    """
    try:
        words = shlex.split(line)
    except ValueError as exc:  # unclosed quote
        output_fn(f"[Error] Unreadable command: {exc}")
        return 2
    command, args = words[0], words[1:]

    if not args:
        output_fn(USAGE[command])
        return 2
    if args[0] in _FORBIDDEN.get(command, ()):
        output_fn(
            f"\"{command} {args[0]}\" never returns: run `sensai-schedule {args[0]}`"
            " in another terminal."
        )
        return 2

    if command == "/schedule":
        # Global options: before the subcommand.
        argv = _with_default(args, "--data-dir", data_dir)
        argv = _with_default(argv, "--host", host)
        argv = _with_default(argv, "--model", model)
        entry = schedule
    else:
        argv = args
        if args[0] == "run":  # `compare` calls no model
            argv = _with_default(argv, "--host", host)
            argv = _with_default(argv, "--judge-model", model)
        entry = evaluate

    try:
        return entry(argv)
    except SystemExit as exc:  # argparse: unknown option, --help
        return exc.code if isinstance(exc.code, int) else 2
    except KeyboardInterrupt:
        output_fn("\nInterrupted.")
        return 130
    except Exception as exc:  # a failing tool must not close the chat
        output_fn(f"[Error] {command} failed: {exc}")
        return 1
