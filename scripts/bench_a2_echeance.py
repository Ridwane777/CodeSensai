"""Item 2 of #87: how long does a real delegation take, and what happens past the deadline?

Run with the real model.
Project read: this repository, read-only.

    python scripts/bench_a2_echeance.py <Ollama host> durations|ghost
    (the former mode names "durees" and "fantome" are still accepted)
"""
# ruff: noqa: E402, E501  (import path added before the imports)
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[1]
_sys.path.insert(0, str(ROOT / "src"))

import sys
import threading
import time

from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.gateway import ToolGateway
from sensai.execution.tool_policy import ToolPreferences
from sensai.tools.delegate_tool import DelegateTool
from sensai.tools.read_file_tool import ReadFileTool

HOST, MODE = sys.argv[1], {"durees": "durations", "fantome": "ghost"}.get(sys.argv[2], sys.argv[2])
MODEL = "qwen3-coder:30b"
import os

PROJECT = os.environ.get("PROJET", str(ROOT))

TASKS = [
    "Read src/sensai/core/structured.py and summarize what this module does in three sentences.",
    "Read src/sensai/tools/delegate_tool.py then src/sensai/execution/gateway.py, and explain how "
    "the gateway runs a tool and why the delegation depth is preserved.",
    "Read src/sensai/knowledge/cache.py and list its public functions and classes, one line each.",
    "Read README.md and give the commands to install and run CodeSensai.",
    "Read src/sensai/web/server.py and list every HTTP route with its method.",
]


class Counting:
    """Gateway that counts and timestamps tool calls (including the sub-agent's)."""

    def __init__(self, gateway):
        self.gateway = gateway
        self.calls = []

    def describe_all(self):
        return self.gateway.describe_all()

    def call(self, name, /, **kwargs):
        self.calls.append((time.monotonic(), name))
        return self.gateway.call(name, **kwargs)


def build(timeout_s):
    registry = ToolRegistry()
    gateway = ToolGateway(registry, ToolPreferences(tool_timeout_s=timeout_s),
                          confirm=lambda request: True)
    counting = Counting(gateway)
    registry.register(ReadFileTool(FilePermissions.for_workspace(PROJECT)))
    registry.register(DelegateTool(HOST, MODEL, counting))
    return counting


if MODE == "durations":
    for task in TASKS:
        tools = build(120)
        start = time.monotonic()
        result = tools.call("delegate_task", task=task)
        took = time.monotonic() - start
        inner = [n for _, n in tools.calls[1:]]
        print(f"{took:6.1f} s  ok={result.ok}  sub-agent calls={inner}", flush=True)
        print(f"         {result.content[:140]!r}", flush=True)

if MODE == "ghost":
    DelegateTool.timeout_s = 38  # deadline: 38 - 30 = 8 s
    tools = build(120)
    start = time.monotonic()
    result = tools.call("delegate_task", task=TASKS[1])
    t_result = time.monotonic() - start
    print(f"result returned to the agent after {t_result:.1f} s: ok={result.ok} {result.content[:120]!r}",
          flush=True)
    before = len(tools.calls)
    time.sleep(90)
    after = [(round(t - start, 1), n) for t, n in tools.calls[before:]]
    print(f"tool calls made AFTER the timeout, in the background: {after}", flush=True)
    print("threads still alive:", [t.name for t in threading.enumerate() if t.daemon], flush=True)
