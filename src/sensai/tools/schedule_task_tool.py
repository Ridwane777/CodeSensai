"""
[X5] Schedule a task from the conversation, in natural language (ADR-0052).

The agent proposes a recurring task ("summarize the TODOs every morning"); it
is only saved with the user's explicit approval, after they see the exact
prompt and frequency. Then `sensai-schedule` (cron or `loop`) runs it,
unattended, with its usual policy (risky actions refused).

Guardrails, because a scheduled task replays its prompt every day with nobody
in front of the screen - the worst case for an instruction hidden in a web page
or a file that was read:
- `write` risk: the gateway ALWAYS asks for approval (no preference can
  loosen this level, `tool_policy.LOOSENABLE`);
- never offered to a scheduled task (`sensai-schedule` only loads
  `build_registry`) nor to a sub-agent (`delegate_tool.NEVER_DELEGATED`);
- the prompt is bounded and cannot itself ask to schedule anything.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.knowledge.memory import ensure_private_dir
from sensai.scheduling.tasks import (
    TASKS_FILE,
    ScheduleStoreError,
    Task,
    TaskStore,
    format_interval,
    parse_interval,
    validate_task_id,
)

MAX_PROMPT_CHARS = 2000


def normalize_id(raw: str) -> str:
    """An id accepted by sensai-schedule (a-z, 0-9, "-", 40 characters).
    Real trial run on 2026-11-01: the model proposed "resume_todo", which was refused."""
    text = unicodedata.normalize("NFKD", str(raw)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].strip("-")


class ScheduleTaskTool:
    name = "schedule_task"
    description = (
        "Propose a recurring task that the agent will run on its own, unattended "
        "(e.g. \"every morning, summarize the TODOs\"). Use it only if the user "
        "explicitly asks to schedule or repeat something. The user "
        "must approve; the task is then run by sensai-schedule. "
        "every : 30m, 1h, 1d, 7d…"
    )
    # Writes durable state that will replay a prompt unattended: approval always required.
    risk = "write"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "id": {"type": "string",
                   "description": "Short id: lowercase letters, digits and \"-\"."},
            "prompt": {"type": "string",
                       "description": "Full instruction, clear without the conversation."},
            "every": {"type": "string", "description": "Frequency: 30m, 1h, 1d, 7d…"},
        },
        "required": ["id", "prompt", "every"],
        "additionalProperties": False,
    }

    def __init__(self, data_dir: str | Path) -> None:
        self.store = TaskStore(Path(data_dir) / "schedule" / TASKS_FILE)

    def describe_call(self, **args: Any) -> str:
        """What the user approves: the task exactly as it will be replayed."""
        try:
            every = format_interval(parse_interval(str(args.get("every", ""))))
        except ValueError:
            every = str(args.get("every", ""))
        return (
            f"Schedule the task \"{normalize_id(args.get('id', ''))}\", every {every}, "
            "run "
            "UNATTENDED by sensai-schedule (risky actions refused):\n\n"
            f"{args.get('prompt', '')}"
        )

    def run(self, **kwargs: Any) -> ToolResult:
        prompt = str(kwargs.get("prompt") or "").strip()
        try:
            task_id = validate_task_id(normalize_id(kwargs.get("id") or ""))
            interval = parse_interval(str(kwargs.get("every") or ""))
            if not prompt:
                raise ValueError("The prompt is empty.")
            if len(prompt) > MAX_PROMPT_CHARS:
                raise ValueError(f"The prompt exceeds {MAX_PROMPT_CHARS} characters.")
            if "schedule_task" in prompt or "/schedule" in prompt:
                raise ValueError("A scheduled task cannot schedule other tasks.")
            ensure_private_dir(self.store.path.parent.parent)
            ensure_private_dir(self.store.path.parent)
            self.store.add(Task(id=task_id, prompt=prompt, interval_s=interval))
        except ScheduleStoreError as e:
            return ToolResult(ok=False, content=f"Unreadable task file: {e}")
        except ValueError as e:
            return ToolResult(ok=False, content=f"Task refused: {e}")
        return ToolResult(
            ok=True,
            content=(f"Task \"{task_id}\" scheduled every {format_interval(interval)}. "
                     "It will run while sensai-schedule loop (or run-due via cron) is running; "
                     "tell the user."),
        )
