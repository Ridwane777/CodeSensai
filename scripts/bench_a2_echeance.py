"""Point 2 de la #87 : combien de temps dure une vraie délégation, et que se passe-t-il au-delà ?

Lancé avec le vrai modèle.
Projet lu : ce dépôt, en lecture seule.

    python scripts/bench_a2_echeance.py <hôte Ollama> durees|fantome
"""
# ruff: noqa: E402, E501  (chemin d'import ajouté avant les imports)
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

HOST, MODE = sys.argv[1], sys.argv[2]
MODEL = "qwen3-coder:30b"
import os

PROJECT = os.environ.get("PROJET", str(ROOT))

TASKS = [
    "Lis src/sensai/core/structured.py et résume ce que fait ce module en trois phrases.",
    "Lis src/sensai/tools/delegate_tool.py puis src/sensai/execution/gateway.py, et explique comment "
    "la passerelle exécute un outil et pourquoi la profondeur de délégation est conservée.",
    "Lis src/sensai/knowledge/cache.py et liste ses fonctions et classes publiques avec une ligne chacune.",
    "Lis README.md et donne les commandes pour installer et lancer CodeSensei.",
    "Lis src/sensai/web/server.py et liste toutes les routes HTTP avec leur méthode.",
]


class Counting:
    """Passerelle qui compte et horodate les appels d'outils (ceux du sous-agent compris)."""

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


if MODE == "durees":
    for task in TASKS:
        tools = build(120)
        start = time.monotonic()
        result = tools.call("delegate_task", task=task)
        took = time.monotonic() - start
        inner = [n for _, n in tools.calls[1:]]
        print(f"{took:6.1f} s  ok={result.ok}  appels du sous-agent={inner}", flush=True)
        print(f"         {result.content[:140]!r}", flush=True)

if MODE == "fantome":
    DelegateTool.timeout_s = 38  # échéance : 38 - 30 = 8 s
    tools = build(120)
    start = time.monotonic()
    result = tools.call("delegate_task", task=TASKS[1])
    t_result = time.monotonic() - start
    print(f"résultat rendu à l'agent après {t_result:.1f} s : ok={result.ok} {result.content[:120]!r}",
          flush=True)
    before = len(tools.calls)
    time.sleep(90)
    after = [(round(t - start, 1), n) for t, n in tools.calls[before:]]
    print(f"appels d'outils faits APRÈS le délai, en arrière-plan : {after}", flush=True)
    print("threads encore vivants :", [t.name for t in threading.enumerate() if t.daemon], flush=True)
