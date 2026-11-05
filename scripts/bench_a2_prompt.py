"""Point 6 de la #87 : le sous-agent doit-il recevoir le prompt du projet ?

Trois tâches, chacune avec et sans le prompt du projet (prompt système, profil,
faits retenus), 3 essais chacune. Base de faits et profil dans un dossier
temporaire : ~/.sensai n'est pas touché.

    python scripts/bench_a2_prompt.py <hôte Ollama>
"""
# ruff: noqa: E402, E501  (chemin d'import ajouté avant les imports)
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
profile = Profile(preferences=["Réponds toujours en anglais."])
base = (PROJECT / "prompts" / "system" / "v1.txt").read_text(encoding="utf-8")
PROJECT_PROMPT = "\n\n".join(p for p in (build_system_prompt(base, profile), facts.as_prompt()) if p)

TASKS = {
    "fait": ("Quelle version de Redis utilise le projet ? Réponds en une phrase.",
             lambda r: bool(re.search(r"\b8\b", r))),
    "profil": ("Explique en deux phrases ce que fait src/sensai/core/structured.py.",
               lambda r: len(re.findall(r"\b(the|and|is|this|module)\b", r.lower()))
               > len(re.findall(r"\b(le|la|et|est|ce|module)\b", r.lower()))),
    "neutre": ("Lis src/sensai/knowledge/cache.py et donne le nom de sa classe principale.",
               lambda r: "AnswerCache" in r),
}


def run(task, with_project):
    registry = ToolRegistry()
    gateway = ToolGateway(registry, None, confirm=lambda request: True)
    registry.register(ReadFileTool(FilePermissions.for_workspace(PROJECT)))
    registry.register(RecallFactsTool(facts))  # comme dans le CLI
    registry.register(DelegateTool(HOST, MODEL, gateway,
                                system_prompt=(lambda: PROJECT_PROMPT) if with_project else None))
    start = time.monotonic()
    result = gateway.call("delegate_task", task=task)
    return time.monotonic() - start, result.content


print(f"prompt du projet : {len(PROJECT_PROMPT)} caractères", flush=True)
for name, (task, check) in [(n, TASKS[n]) for n in sys.argv[2:] or TASKS]:
    for with_project in (False, True):
        ok, times, sample = 0, [], ""
        for _ in range(RUNS):
            took, reply = run(task, with_project)
            times.append(took)
            ok += check(reply)
            sample = reply
        label = "avec le prompt du projet" if with_project else "sans (persona seul)"
        print(f"{name:7} {label:26} réussi {ok}/{RUNS}  durée moyenne {sum(times)/RUNS:5.1f} s"
              f"  ex. : {sample[:90]!r}", flush=True)
