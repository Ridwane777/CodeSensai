"""
A2 measurements (multi-agent orchestration, ADR-0038) with the real model, in a
throwaway project (temporary directory): the repository is never modified.
Results and choices: docs/performance/A2-orchestration.md.

    python scripts/bench_a2.py <Ollama host> roles|team|review|choice|detail [runs]

roles  : explorer and reviewer asked to write -> refusal expected.
team   : team_task on three checkable tasks; the final code is executed.
review : the reviewer gets wrong work (CASE=wrong) or correct work (CASE=right).
choice : does the main agent (system prompt v2) hand code to the team,
         and answer questions on its own?
detail : full team report on one task (TASK=...).
The former French mode names (equipe, critique, choix) and variables (CAS=faux|juste,
TACHE) are still accepted. Role ids ("explorateur", "relecteur") are the ids defined
in src/sensai/tools/delegate_tool.py.
"""
# ruff: noqa: E402, E501  (import path added before the imports; one-line datasets)
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import shutil
import subprocess
import tempfile
import time

from sensai.core.agent import run_agent_turn
from sensai.core.events import ToolCall
from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.gateway import ToolGateway
from sensai.tools.delegate_tool import DelegateTool
from sensai.tools.read_file_tool import ReadFileTool
from sensai.tools.team_tool import TeamTool, review_request, verdict
from sensai.tools.write_file_tool import WriteFileTool

HOST = sys.argv[1]
MODE = {"equipe": "team", "critique": "review", "choix": "choice"}.get(sys.argv[2], sys.argv[2])
RUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
MODEL = "qwen3-coder:30b"
SYSTEM_V2 = (ROOT / "prompts/system/v2.txt").read_text(encoding="utf-8") + os.environ.get("EXTRA", "")

STATS = '''def mean(values):
    """Arithmetic mean of a non-empty list."""
    return sum(values) / (len(values) + 1)


def maximum(values):
    """Largest value of a non-empty list."""
    largest = 0
    for v in values:
        if v > largest:
            largest = v
    return largest
'''

# (task, check run against the final file)
TASKS = [
    ("Fix the bug in the mean function in stats.py (the file is at the project "
     "root) and rewrite the file with write_file.",
     "from stats import mean; assert mean([2, 4]) == 3"),
    ("Fix the maximum function in stats.py so it also works with negative "
     "numbers, then rewrite the file with write_file.",
     "from stats import maximum; assert maximum([-5, -2, -9]) == -2; assert maximum([1, 7]) == 7"),
    ("Add a median(values) function to stats.py (non-empty list, even or odd number "
     "of values) without breaking the rest, then rewrite the file with write_file.",
     "from stats import median; assert median([3, 1, 2]) == 2; assert median([4, 1, 3, 2]) == 2.5"),
]


def project():
    root = Path(tempfile.mkdtemp(prefix="sensai-team-"))
    (root / "stats.py").write_text(STATS, encoding="utf-8")
    return root


class Counting:
    def __init__(self, gateway):
        self.gateway, self.calls = gateway, []

    def describe_all(self):
        return self.gateway.describe_all()

    def call(self, name, /, **kwargs):
        self.calls.append(name)
        return self.gateway.call(name, **kwargs)


def build(root, notes=None):
    registry = ToolRegistry()
    executed = []

    def confirm(request):
        executed.append(request.tool)
        return True

    gateway = ToolGateway(registry, None, confirm=confirm)
    counting = Counting(gateway)
    perms = FilePermissions.for_workspace(root)
    registry.register(ReadFileTool(perms))
    registry.register(WriteFileTool(perms))
    delegate = DelegateTool(HOST, MODEL, counting)
    registry.register(delegate)
    registry.register(TeamTool(delegate, notify=notes.append if notes is not None else None))
    return counting, executed


def check(root, code):
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    return r.returncode == 0


if MODE == "roles":
    for role in ("explorateur", "relecteur"):
        for _ in range(RUNS):
            root = project()
            tools, confirmed = build(root)
            start = time.monotonic()
            result = tools.call("delegate_task", role=role,
                                task="Create the file notes.md containing \"hello\" with write_file.")
            took = time.monotonic() - start
            print(f"{role:11} {took:5.1f} s  calls={tools.calls[1:]}  confirmations={confirmed[1:]}"
                  f"  notes.md created={(root / 'notes.md').exists()}  | {result.content[:80]!r}",
                  flush=True)
            shutil.rmtree(root)

if MODE == "team":
    for task, code in TASKS:
        for _ in range(RUNS):
            root = project()
            notes = []
            tools, confirmed = build(root, notes)
            start = time.monotonic()
            result = tools.call("team_task", task=task)
            took = time.monotonic() - start
            first = result.content.splitlines()[0] if result.content else ""
            print(f"{took:5.1f} s  ok={result.ok}  code correct={check(root, code)}  "
                  f"writes={confirmed.count('write_file')}  | {first[:120]}", flush=True)
            shutil.rmtree(root)

if MODE == "choice":
    prompts = [
        ("code", "Fix the bug in the mean function in stats.py."),
        ("code", "The maximum function in stats.py is wrong with negative numbers, fix it."),
        ("code", "Add a median function to stats.py."),
        ("code", "Add more detailed docstrings to the functions in stats.py."),
        ("code", "Make mean raise a ValueError on an empty list in stats.py."),
        ("question", "What does the mean function in stats.py do?"),
        ("question", "Explain the difference between a mean and a median."),
        ("question", "Read stats.py and tell me how many functions it has."),
    ]
    for kind, prompt in prompts:
        root = project()
        tools, _ = build(root)
        messages = [{"role": "system", "content": SYSTEM_V2}, {"role": "user", "content": prompt}]
        start = time.monotonic()
        names = [e.name for e in run_agent_turn(HOST, MODEL, messages, tools)
                 if isinstance(e, ToolCall)]
        took = time.monotonic() - start
        print(f"{kind:8} {took:5.1f} s  team={'team_task' in names}  tools={names}"
              f"  | {prompt[:50]}", flush=True)
        shutil.rmtree(root)

# Does the reviewer spot wrong work? It gets a file left buggy (or badly
# fixed) with a report claiming it is fixed.
WRONG = [
    ("Fix the bug in the mean function in stats.py.", STATS,
     "I fixed mean in stats.py: the file has been rewritten."),
    ("Fix maximum in stats.py for negative numbers.",
     STATS.replace("largest = 0", "largest = -1"),
     "I fixed maximum: the starting value is now -1, rewritten with write_file."),
]
RIGHT = [
    ("Fix the bug in the mean function in stats.py.",
     STATS.replace("(len(values) + 1)", "len(values)"),
     "I fixed mean in stats.py: division by len(values)."),
    ("Fix maximum in stats.py for negative numbers.",
     STATS.replace("largest = 0", "largest = values[0]"),
     "I fixed maximum: the starting value is the first element."),
]
if MODE == "review":
    case = os.environ.get("CASE", os.environ.get("CAS", "wrong"))
    cases = WRONG if case in ("wrong", "faux") else RIGHT
    for task, content, claim in cases:
        for _ in range(RUNS):
            root = project()
            (root / "stats.py").write_text(content, encoding="utf-8")
            tools, _ = build(root)
            delegate = DelegateTool(HOST, MODEL, tools)
            start = time.monotonic()
            r = delegate.delegate(review_request(task, claim, {"stats.py": content}),
                                  role="relecteur")
            print(f"{time.monotonic() - start:5.1f} s  verdict={verdict(r.content)}  "
                  f"reads={tools.calls.count('read_file')}  | {r.content[:90]!r}", flush=True)
            shutil.rmtree(root)

if MODE == "detail":
    task = os.environ.get("TASK", os.environ.get("TACHE", "Add more detailed docstrings to the functions in stats.py."))
    for i in range(RUNS):
        root = project()
        notes = []
        tools, confirmed = build(root, notes)
        start = time.monotonic()
        result = tools.call("team_task", task=task)
        print(f"\n######## run {i + 1}: {time.monotonic() - start:.1f} s ok={result.ok} "
              f"writes={confirmed.count('write_file')} handoffs={notes}", flush=True)
        print(result.content[:4000], flush=True)
        print("--- final stats.py:\n" + (root / "stats.py").read_text(encoding="utf-8")[:1500])
        shutil.rmtree(root)
