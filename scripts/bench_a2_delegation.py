"""A2 trial runs (PR #87) with the real model: re-delegation, appropriate delegation,
late confirmations.

    python scripts/bench_a2_delegation.py <Ollama host> redelegation|appropriate|late
    (the former mode names "escient" and "tardive" are still accepted)
"""
# ruff: noqa: E402, E501  (import path added before the imports)
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[1]
_sys.path.insert(0, str(ROOT / "src"))

import os
import re
import sys
import time

from sensai.core.agent import run_agent_turn
from sensai.core.events import ToolCall
from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.gateway import ToolGateway
from sensai.execution.tool_policy import ToolPreferences
from sensai.tools import delegate_tool
from sensai.tools.delegate_tool import DelegateTool
from sensai.tools.read_file_tool import ReadFileTool
from sensai.tools.write_file_tool import WriteFileTool

HOST, MODE = sys.argv[1], {"escient": "appropriate", "tardive": "late"}.get(sys.argv[2], sys.argv[2])
MODEL = "qwen3-coder:30b"
PROJECT = ROOT
SYSTEM = (PROJECT / "prompts" / "system" / "v1.txt").read_text(encoding="utf-8") + os.environ.get("EXTRA", "")
T0 = time.monotonic()


def now():
    return round(time.monotonic() - T0, 1)


class Counting:
    def __init__(self, gateway):
        self.gateway, self.calls = gateway, []

    def describe_all(self):
        return self.gateway.describe_all()

    def call(self, name, /, **kwargs):
        self.calls.append(name)
        return self.gateway.call(name, **kwargs)


def tools(timeout_s=120, confirm=lambda request: True, write=False):
    registry = ToolRegistry()
    gateway = ToolGateway(registry, ToolPreferences(tool_timeout_s=timeout_s), confirm=confirm)
    counting = Counting(gateway)
    perms = FilePermissions.for_workspace(PROJECT)
    registry.register(ReadFileTool(perms))
    if write:
        registry.register(WriteFileTool(perms))
    registry.register(DelegateTool(HOST, MODEL, counting))
    return counting


# 1. Does re-delegating ever help? Tasks that split up, depth 2 then 1.
SPLIT = [
    ("Analyze src/sensai/knowledge/cache.py, src/sensai/knowledge/facts.py and "
     "src/sensai/knowledge/state_document.py, then compare how they store data.",
     [r"sqlite|\.db\b", r"jsonl|journal|log", r"SENSAI\.md|markdown"]),
    ("For each of these files, say in one sentence what it does: src/sensai/web/server.py, "
     "src/sensai/web/runtime.py, src/sensai/web/cli.py, src/sensai/core/structured.py.",
     [r"server\.py", r"runtime\.py", r"cli\.py", r"structured\.py"]),
]

if MODE == "redelegation":
    for depth in (delegate_tool.MAX_DELEGATION_DEPTH,):
        for task, checks in SPLIT:
            for _ in range(2):
                t = tools()
                start = time.monotonic()
                result = t.call("delegate_task", task=task)
                took = time.monotonic() - start
                score = sum(bool(re.search(c, result.content, re.I)) for c in checks)
                print(f"depth {depth}  {took:5.1f} s  quality {score}/{len(checks)}  "
                      f"nested delegations {t.calls.count('delegate_task') - 1}  "
                      f"reads {t.calls.count('read_file')}", flush=True)

# 2. Does the main agent delegate when it should?
SIMPLE = [
    "What does the conflict function in src/sensai/knowledge/cache.py do?",
    "What is the value of MAX_MESSAGE_CHARS in src/sensai/web/server.py?",
    "Read README.md and tell me how to run the tests.",
    "What is DEFAULT_THRESHOLD in src/sensai/knowledge/cache.py?",
    "What does the /api/health route return?",
]
SPLITTABLE = [t for t, _ in SPLIT] + [
    "Read the five files in src/sensai/web/ and src/sensai/tools/delegate_tool.py, then "
    "summarize the architecture of the web server and of delegation.",
    "Compare src/sensai/knowledge/rag.py and src/sensai/knowledge/retrieval.py: role, inputs, outputs.",
    "Check in src/sensai/execution/gateway.py, src/sensai/execution/tool_policy.py and "
    "src/sensai/execution/web_confirmation.py how a risky action is confirmed.",
]
EXPLICIT = [
    "Delegate the analysis of src/sensai/knowledge/cache.py to a sub-agent and summarize its answer.",
    "Use sub-agents: one for src/sensai/web/server.py, one for src/sensai/web/runtime.py, "
    "then compare.",
    "Have a sub-agent list the routes in src/sensai/web/server.py.",
]

if MODE == "appropriate":
    for kind, prompts in [k for k in (("simple", SIMPLE), ("splittable", SPLITTABLE), ("explicit", EXPLICIT)) if k[0] in os.environ.get("KINDS", "simple splittable explicit")]:
        delegated = 0
        for prompt in prompts:
            t = tools()
            messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
            start = time.monotonic()
            names = [e.name for e in run_agent_turn(HOST, MODEL, messages, t)
                     if isinstance(e, ToolCall)]
            took = time.monotonic() - start
            d = names.count("delegate_task")
            delegated += d > 0
            print(f"{kind:10} {took:5.1f} s  delegates={d}  tools={names}  | {prompt[:60]}", flush=True)
        print(f"==> {kind}: delegated in {delegated}/{len(prompts)} requests", flush=True)

# 3. Can a confirmation arrive after the sub-agent gave up?
if MODE == "late":
    asked = []

    def confirm(request):
        asked.append((now(), request.tool))
        return request.tool == "delegate_task"  # yes to delegate, no to write

    DelegateTool.timeout_s = 40  # sub-agent deadline: 40 - 30 = 10 s
    t = tools(timeout_s=120, confirm=confirm, write=True)
    task = ("Read src/sensai/knowledge/cache.py, src/sensai/knowledge/facts.py and "
            "src/sensai/web/server.py, then write a summary of each to notes_tmp.md with write_file.")
    result = t.call("delegate_task", task=task)
    print(f"delegation returned at {now()} s : ok={result.ok}", flush=True)
    time.sleep(150)
    print(f"confirmations requested (time, tool): {asked}", flush=True)
    print(f"of which after giving up: {[a for a in asked if a[0] > 10.5]}", flush=True)
    print(f"notes_tmp.md created: {(PROJECT / 'notes_tmp.md').exists()}", flush=True)
