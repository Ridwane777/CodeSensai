"""Item 6 of #87: should the sub-agent receive the project prompt?

Three tasks, each with and without the project prompt (system prompt, profile,
remembered facts), 3 trial runs each. Fact store and profile live in a temporary
directory: ~/.sensai is not touched.

    python scripts/bench_a2_prompt.py <Ollama host>
"""
# ruff: noqa: E402, E501  (import path added before the imports)
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[1]
_sys.path.insert(0, str(ROOT / "src"))

import re
import sys
import tempfile
import time
from pathlib import Path

from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.gateway import ToolGateway
from sensai.knowledge.facts import FactStore
from sensai.knowledge.memory import Profile, build_system_prompt
from sensai.tools.delegate_tool import DelegateTool
from sensai.tools.fact_tools import RecallFactsTool
from sensai.tools.read_file_tool import ReadFileTool

HOST = sys.argv[1]
MODEL = "qwen3-coder:30b"
PROJECT = ROOT
RUNS = 3

tmp = Path(tempfile.mkdtemp())
facts = FactStore(tmp / "memory.db", str(PROJECT))
facts.remember("redis", "version", "8")
profile = Profile(preferences=["Always answer in French."])
base = (PROJECT / "prompts" / "system" / "v1.txt").read_text(encoding="utf-8")
PROJECT_PROMPT = "\n\n".join(p for p in (build_system_prompt(base, profile), facts.as_prompt()) if p)

TASKS = {
    "fact": ("Which Redis version does the project use? Answer in one sentence.",
             lambda r: bool(re.search(r"\b8\b", r))),
    # The profile asks for French while the task is in English: a French answer proves the profile was applied.
    "profile": ("Explain in two sentences what src/sensai/core/structured.py does.",
                lambda r: len(re.findall(r"\b(le|la|et|est|ce|module)\b", r.lower()))
                > len(re.findall(r"\b(the|and|is|this|module)\b", r.lower()))),
    "neutral": ("Read src/sensai/knowledge/cache.py and give the name of its main class.",
               lambda r: "AnswerCache" in r),
}


def run(task, with_project):
    registry = ToolRegistry()
    gateway = ToolGateway(registry, None, confirm=lambda request: True)
    registry.register(ReadFileTool(FilePermissions.for_workspace(PROJECT)))
    registry.register(RecallFactsTool(facts))  # as in the CLI
    registry.register(DelegateTool(HOST, MODEL, gateway,
                                system_prompt=(lambda: PROJECT_PROMPT) if with_project else None))
    start = time.monotonic()
    result = gateway.call("delegate_task", task=task)
    return time.monotonic() - start, result.content


print(f"project prompt: {len(PROJECT_PROMPT)} characters", flush=True)
for name, (task, check) in [(n, TASKS[n]) for n in sys.argv[2:] or TASKS]:
    for with_project in (False, True):
        ok, times, sample = 0, [], ""
        for _ in range(RUNS):
            took, reply = run(task, with_project)
            times.append(took)
            ok += check(reply)
            sample = reply
        label = "with project prompt" if with_project else "without (persona only)"
        print(f"{name:7} {label:26} passed {ok}/{RUNS}  mean duration {sum(times)/RUNS:5.1f} s"
              f"  e.g.: {sample[:90]!r}", flush=True)
