"""Essais A2 (PR #87), avec le vrai modèle : redélégation, délégation à bon escient,
confirmations tardives.

    python scripts/bench_a2_delegation.py <hôte Ollama> redelegation|escient|tardive
"""
# ruff: noqa: E402, E501  (chemin d'import ajouté avant les imports)
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

HOST, MODE = sys.argv[1], sys.argv[2]
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


# 1. Redéléguer aide-t-il parfois ? Tâches qui se découpent, profondeur 2 puis 1.
SPLIT = [
    ("Analyse src/sensai/knowledge/cache.py, src/sensai/knowledge/facts.py et "
     "src/sensai/knowledge/state_document.py, puis compare leur façon de stocker les données.",
     [r"sqlite|\.db\b", r"jsonl|journal", r"SENSAI\.md|markdown"]),
    ("Pour chacun de ces fichiers, dis en une phrase à quoi il sert : src/sensai/web/server.py, "
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
                print(f"profondeur {depth}  {took:5.1f} s  qualité {score}/{len(checks)}  "
                      f"délégations internes {t.calls.count('delegate_task') - 1}  "
                      f"lectures {t.calls.count('read_file')}", flush=True)

# 2. L'agent principal délègue-t-il à bon escient ?
SIMPLE = [
    "Que fait la fonction conflict dans src/sensai/knowledge/cache.py ?",
    "Quelle est la valeur de MAX_MESSAGE_CHARS dans src/sensai/web/server.py ?",
    "Lis README.md et dis-moi comment lancer les tests.",
    "Combien vaut DEFAULT_THRESHOLD dans src/sensai/knowledge/cache.py ?",
    "Que renvoie la route /api/health ?",
]
SPLITTABLE = [t for t, _ in SPLIT] + [
    "Lis les cinq fichiers de src/sensai/web/ et src/sensai/tools/delegate_tool.py, puis fais un "
    "résumé de l'architecture du serveur web et de la délégation.",
    "Compare src/sensai/knowledge/rag.py et src/sensai/knowledge/retrieval.py : rôle, entrées, sorties.",
    "Vérifie dans src/sensai/execution/gateway.py, src/sensai/execution/tool_policy.py et "
    "src/sensai/execution/web_confirmation.py comment une action risquée est confirmée.",
]
EXPLICIT = [
    "Délègue à un sous-agent l'analyse de src/sensai/knowledge/cache.py et résume sa réponse.",
    "Utilise des sous-agents : un pour src/sensai/web/server.py, un pour src/sensai/web/runtime.py, "
    "puis compare.",
    "Fais faire par un sous-agent la liste des routes de src/sensai/web/server.py.",
]

if MODE == "escient":
    for kind, prompts in [k for k in (("simple", SIMPLE), ("découpable", SPLITTABLE), ("explicite", EXPLICIT)) if k[0] in os.environ.get("KINDS", "simple découpable explicite")]:
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
            print(f"{kind:10} {took:5.1f} s  délègue={d}  outils={names}  | {prompt[:60]}", flush=True)
        print(f"==> {kind} : délégation dans {delegated}/{len(prompts)} demandes", flush=True)

# 3. Une confirmation peut-elle arriver après l'abandon du sous-agent ?
if MODE == "tardive":
    asked = []

    def confirm(request):
        asked.append((now(), request.tool))
        return request.tool == "delegate_task"  # oui pour déléguer, non pour écrire

    DelegateTool.timeout_s = 40  # échéance du sous-agent : 40 - 30 = 10 s
    t = tools(timeout_s=120, confirm=confirm, write=True)
    task = ("Lis src/sensai/knowledge/cache.py, src/sensai/knowledge/facts.py et "
            "src/sensai/web/server.py, puis écris un résumé de chacun dans notes_tmp.md avec write_file.")
    result = t.call("delegate_task", task=task)
    print(f"délégation rendue à {now()} s : ok={result.ok}", flush=True)
    time.sleep(150)
    print(f"confirmations demandées (instant, outil) : {asked}", flush=True)
    print(f"dont après l'abandon : {[a for a in asked if a[0] > 10.5]}", flush=True)
    print(f"notes_tmp.md créé : {(PROJECT / 'notes_tmp.md').exists()}", flush=True)
