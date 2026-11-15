"""
A team of specialized agents that hand work to each other - feature [A2]
Multi-Agent Orchestration (ADR-0038).

`team_task` chains three specialized agents (roles defined in
delegate_tool.ROLES): the explorer gathers context, the developer produces the
change from that report, the reviewer critiques it. If the reviewer answers
"NEEDS FIX", the work goes back to the developer once with the critique, then
back to the reviewer. Each agent is a DelegateTool sub-agent: same gateway,
same confirmations, only the tools of its role, and no re-delegation.

The whole chain fits within a single tool's timeout (the gateway abandons it
beyond that): each step gets the remaining time, and the chain stops and says
so if time runs out.
"""
from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any, ClassVar

from sensai.core.tools import ToolResult
from sensai.tools.delegate_tool import (
    DELEGATION_TIMEOUT_S,
    MAX_DELEGATION_DEPTH,
    STOP_MARGIN_S,
    DelegateTool,
    _depth,
)

MAX_CORRECTIONS = 1
# Below this, starting one more step is pointless: a single model call often
# takes that long (measured: 6 to 30 s per sub-agent).
MIN_STEP_S = 10.0
# Beyond this, the content of a written file is truncated in the reviewer instruction.
MAX_REVIEWED_CHARS = 12_000


# A file name mentioned in the task: "stats.py", "src/app/main.ts"...
_FILE_NAME = re.compile(r"(?<![\w/.-])([\w./-]*\w\.[A-Za-z0-9]{1,5})(?![\w/-])")


def named_files(task: str) -> set[str]:
    """The files the task names, as written (without "./")."""
    return {m.removeprefix("./") for m in _FILE_NAME.findall(task)}


def misplaced(task: str, created: set[str]) -> list[tuple[str, str]]:
    """(created file, requested file): a CREATED file that has the name of a
    file mentioned in the task, but somewhere else. Trial run of 2026-11-01: for
    "add mediane to stats.py", the developer created src/sensai/stats.py, the
    reviewer approved it, and the agent announced that stats.py was modified."""
    out = []
    for path in sorted(created):
        clean = path.removeprefix("./")
        for name in named_files(task):
            if PurePosixPath(clean).name == PurePosixPath(name).name and clean != name:
                out.append((path, name))
    return out


def review_request(task: str, work: str, written: dict[str, str]) -> str:
    """The reviewer instruction: the task, the developer report and above all
    the content ACTUALLY written. Measured with the real model: with the report
    alone, the reviewer approved wrong work 6 times out of 6, without reading anything."""
    if written:
        files = "\n\n".join(
            f"### {path}\n```\n{content[:MAX_REVIEWED_CHARS]}\n```"
            for path, content in written.items()
        )
        evidence = f"Files actually written by the developer (exact content):\n{files}"
    else:
        evidence = "The developer wrote no file."
    names = sorted(named_files(task))
    target = (f"\n\nFiles the task asks to modify: {', '.join(names)}. Check that "
              "these are the ones that were written, at this exact path; otherwise, NEEDS FIX."
              if names else "")
    return (
        f"Task: {task}\n\nDeveloper report (do not take it at face value):\n"
        f"{work}\n\n{evidence}{target}\n\nJudge the code above, not the report: "
        "try it mentally on a few examples, including edge cases."
    )


def verdict(review: str) -> str:
    """"approved", "needs fix" or "unreadable", from the start of the review.

    French answers (VALIDÉ / À CORRIGER) are still accepted: the model sometimes
    replies in the user's language."""
    head = unicodedata.normalize("NFKD", review.strip()[:40]).encode("ascii", "ignore")
    text = head.decode().upper().lstrip("*#> ")
    if text.startswith(("APPROVED", "VALIDE")):
        return "approved"
    if text.startswith(("NEEDS FIX", "A CORRIGER")):
        return "needs fix"
    return "unreadable"


class TeamTool:
    name = "team_task"
    description = (
        "Hands a code change to a team of three specialized agents that pass the work "
        "along: an explorer reads the relevant code, a developer makes the change, a "
        "reviewer checks it (and sends it back to the developer if it finds a defect). "
        "Use it to write or fix code when verification matters, or when the user asks "
        "for the team. Not for a simple question."
    )
    # The developer can write and execute: same reasoning as delegate_task.
    risk = "execute"
    timeout_s = DELEGATION_TIMEOUT_S
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "The complete task, phrased to be understood without the current "
                    "conversation (files involved, expected result)."
                ),
            },
        },
        "required": ["task"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        delegate: DelegateTool,
        notify: Callable[[str], None] | None = None,
        on_handoff: Callable[[str], None] | None = None,
        test_runner: Callable[[], tuple[bool, str]] | None = None,
    ):
        self.delegate = delegate
        # The project tests, if any (ADR-0056, point 3): they replace the
        # reviewer verdict, which approved wrong work during trial runs.
        self.test_runner = test_runner
        # Shows each handoff while the work runs (the terminal, in the CLI).
        self.notify = notify or (lambda message: None)
        # The same handoff, in structured form: the role taking over
        # (the web turns it into an `agent_handoff` event, X1).
        self.on_handoff = on_handoff or (lambda role: None)

    def describe_call(self, **args: Any) -> str:
        task = args.get("task", "")
        return f"Hand to the team (explorer → developer → reviewer): {task}"

    def run(self, **kwargs) -> ToolResult:
        task = (kwargs.get("task") or "").strip()
        if not task:
            return ToolResult(ok=False, content="The task is empty.")
        if _depth.get() >= MAX_DELEGATION_DEPTH:
            return ToolResult(ok=False, content="A sub-agent does not start a team.")

        deadline = time.monotonic() + self.timeout_s - STOP_MARGIN_S
        path: list[str] = []
        steps: list[tuple[str, str]] = []
        written: dict[str, str] = {}
        created: set[str] = set()

        def record(name: str, args: dict, result: ToolResult) -> None:
            if name == "write_file" and result.ok and "path" in args:
                written[str(args["path"])] = str(args.get("content", ""))
                if str(result.content).startswith("Created"):
                    created.add(str(args["path"]))

        def step(role: str, instruction: str) -> ToolResult | None:
            if deadline - time.monotonic() < MIN_STEP_S:
                return None
            if path:
                self.notify(f"handoff: {path[-1]} → {role}")
            else:
                self.notify(f"team: {role} at work")
            path.append(role)
            self.on_handoff(role)
            result = self.delegate.delegate(instruction, role=role, deadline=deadline, on_call=record)
            steps.append((role, result.content))
            return result

        def stopped(at: str) -> ToolResult:
            return self._report(path, steps, f"stopped for lack of time before {at}", ok=False)

        report = step("explorateur", f"Team task: {task}\n\nGather the useful context.")
        if report is None:
            return stopped("the explorer")
        context = report.content if report.ok else "(the explorer could not report anything)"

        work = step(
            "developpeur",
            f"Task: {task}\n\nExplorer report:\n{context}\n\nMake the change.",
        )
        if work is None:
            return stopped("the developer")

        state = "unreadable"
        wrong: list[tuple[str, str]] = []
        for attempt in range(MAX_CORRECTIONS + 1):
            wrong = misplaced(task, created)
            if self.test_runner is not None and not written:
                # The tests of an unchanged project pass: they prove nothing. Trial
                # run of 2026-11-06: write refused, and yet "approved".
                critique = ("NEEDS FIX. No file was modified: read the relevant files, "
                            "then make the change with write_file.")
                state = "needs fix"
            elif wrong:
                # Mechanical check, before any review: a file written in the wrong
                # place need not be judged, it is sent back as is.
                critique = "NEEDS FIX. " + "; ".join(
                    f"you created {made} instead of modifying {asked}: read {asked}, then "
                    f"rewrite it with write_file (overwrite set to true)" for made, asked in wrong)
                state = "needs fix"
            elif self.test_runner is not None:
                self.notify("team: project tests")
                passed, output = self.test_runner()
                steps.append(("project tests", output or "(no output)"))
                state = "approved" if passed else "needs fix"
                critique = f"NEEDS FIX. The project tests fail:\n{output}"
            else:
                review = step("relecteur", review_request(task, work.content, written))
                if review is None:
                    return stopped("the reviewer")
                state = verdict(review.content) if review.ok else "unreadable"
                critique = review.content
            if state != "needs fix" or attempt == MAX_CORRECTIONS:
                break
            created.clear()
            work = step(
                "developpeur",
                f"Task: {task}\n\nYour previous work:\n{work.content}\n\n"
                f"Critique:\n{critique}\n\nFix these defects.",
            )
            if work is None:
                return stopped("the developer fix")
        wrong = misplaced(task, created)
        if wrong:
            state = "needs fix"
        judge = "project tests" if self.test_runner is not None else "reviewer"
        end = f"{judge} verdict: {state}"
        if self.test_runner is not None and not written:
            state = "needs fix"
            end = "verdict: needs fix - no file modified, the tests were not run"
        if wrong:
            end = ("verdict: needs fix - file written in the wrong place: " + ", ".join(
                f"{made} (the task asked for {asked}, which was not modified)"
                for made, asked in wrong))
        if state != "approved":
            # The chain did its job: this is a result, not a failure. Measured with
            # the real model: returned as a failure, the main agent restarted the team
            # (3 times, 190 s) instead of passing the remarks on.
            end += "; do not restart the team, pass these remarks on to the user"
        return self._report(path, steps, end, ok=True)

    @staticmethod
    def _report(path: list[str], steps: list[tuple[str, str]], end: str, ok: bool) -> ToolResult:
        lines = [f"Path: {' → '.join(path) or '(no agent started)'}; {end}."]
        lines += [f"\n## {role}\n{content}" for role, content in steps]
        return ToolResult(ok=ok, content="\n".join(lines))
