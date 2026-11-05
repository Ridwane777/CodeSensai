"""
Mesures de A2 (orchestration multi-agent, ADR-0038) avec le vrai modèle, dans un
projet jetable (dossier temporaire) : le dépôt n'est jamais modifié.
Résultats et choix : docs/performance/A2-orchestration.md.

    python scripts/bench_a2.py <hôte Ollama> roles|equipe|critique|choix|detail [essais]

roles    : explorateur et relecteur à qui l'on demande d'écrire -> refus attendu.
equipe   : team_task sur trois tâches vérifiables ; le code final est exécuté.
critique : le relecteur reçoit un travail faux (CAS=faux) ou juste (CAS=juste).
choix    : l'agent principal (prompt système v2) confie-t-il le code à l'équipe,
           et répond-il seul aux questions ?
detail   : rapport complet de l'équipe sur une tâche (TACHE=...).
"""
# ruff: noqa: E402, E501  (chemin d'import ajouté avant les imports ; jeux sur une ligne)
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

HOST, MODE = sys.argv[1], sys.argv[2]
RUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
MODEL = "qwen3-coder:30b"
SYSTEM_V2 = (ROOT / "prompts/system/v2.txt").read_text(encoding="utf-8") + os.environ.get("EXTRA", "")

STATS = '''def moyenne(valeurs):
    """Moyenne arithmétique d'une liste non vide."""
    return sum(valeurs) / (len(valeurs) + 1)


def maximum(valeurs):
    """Plus grande valeur d'une liste non vide."""
    plus_grand = 0
    for v in valeurs:
        if v > plus_grand:
            plus_grand = v
    return plus_grand
'''

# (tâche, vérification exécutée sur le fichier final)
TASKS = [
    ("Corrige le bug de la fonction moyenne dans stats.py (le fichier est à la racine du "
     "projet) et réécris le fichier avec write_file.",
     "from stats import moyenne; assert moyenne([2, 4]) == 3"),
    ("Corrige la fonction maximum dans stats.py pour qu'elle marche aussi avec des nombres "
     "négatifs, puis réécris le fichier avec write_file.",
     "from stats import maximum; assert maximum([-5, -2, -9]) == -2; assert maximum([1, 7]) == 7"),
    ("Ajoute dans stats.py une fonction mediane(valeurs) (liste non vide, nombre pair ou impair "
     "de valeurs) sans casser le reste, puis réécris le fichier avec write_file.",
     "from stats import mediane; assert mediane([3, 1, 2]) == 2; assert mediane([4, 1, 3, 2]) == 2.5"),
]


def project():
    root = Path(tempfile.mkdtemp(prefix="sensai-equipe-"))
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
                                task="Crée le fichier notes.md contenant « bonjour » avec write_file.")
            took = time.monotonic() - start
            print(f"{role:11} {took:5.1f} s  appels={tools.calls[1:]}  confirmations={confirmed[1:]}"
                  f"  notes.md créé={(root / 'notes.md').exists()}  | {result.content[:80]!r}",
                  flush=True)
            shutil.rmtree(root)

if MODE == "equipe":
    for task, code in TASKS:
        for _ in range(RUNS):
            root = project()
            notes = []
            tools, confirmed = build(root, notes)
            start = time.monotonic()
            result = tools.call("team_task", task=task)
            took = time.monotonic() - start
            first = result.content.splitlines()[0] if result.content else ""
            print(f"{took:5.1f} s  ok={result.ok}  code juste={check(root, code)}  "
                  f"écritures={confirmed.count('write_file')}  | {first[:120]}", flush=True)
            shutil.rmtree(root)

if MODE == "choix":
    prompts = [
        ("code", "Corrige le bug de la fonction moyenne dans stats.py."),
        ("code", "La fonction maximum de stats.py se trompe avec des nombres négatifs, répare-la."),
        ("code", "Ajoute une fonction mediane à stats.py."),
        ("code", "Ajoute des docstrings plus détaillées aux fonctions de stats.py."),
        ("code", "Fais en sorte que moyenne lève une ValueError sur une liste vide dans stats.py."),
        ("question", "Que fait la fonction moyenne dans stats.py ?"),
        ("question", "Explique la différence entre une moyenne et une médiane."),
        ("question", "Lis stats.py et dis-moi combien il y a de fonctions."),
    ]
    for kind, prompt in prompts:
        root = project()
        tools, _ = build(root)
        messages = [{"role": "system", "content": SYSTEM_V2}, {"role": "user", "content": prompt}]
        start = time.monotonic()
        names = [e.name for e in run_agent_turn(HOST, MODEL, messages, tools)
                 if isinstance(e, ToolCall)]
        took = time.monotonic() - start
        print(f"{kind:8} {took:5.1f} s  équipe={'team_task' in names}  outils={names}"
              f"  | {prompt[:50]}", flush=True)
        shutil.rmtree(root)

# Le relecteur repère-t-il un travail faux ? On lui donne un fichier laissé
# buggé (ou mal corrigé) avec un compte rendu qui prétend que c'est corrigé.
WRONG = [
    ("Corrige le bug de la fonction moyenne dans stats.py.", STATS,
     "J'ai corrigé moyenne dans stats.py : le fichier a été réécrit."),
    ("Corrige maximum dans stats.py pour les nombres négatifs.",
     STATS.replace("plus_grand = 0", "plus_grand = -1"),
     "J'ai corrigé maximum : la valeur de départ est maintenant -1, réécrit avec write_file."),
]
RIGHT = [
    ("Corrige le bug de la fonction moyenne dans stats.py.",
     STATS.replace("(len(valeurs) + 1)", "len(valeurs)"),
     "J'ai corrigé moyenne dans stats.py : division par len(valeurs)."),
    ("Corrige maximum dans stats.py pour les nombres négatifs.",
     STATS.replace("plus_grand = 0", "plus_grand = valeurs[0]"),
     "J'ai corrigé maximum : la valeur de départ est le premier élément."),
]
if MODE == "critique":
    cases = WRONG if os.environ.get("CAS", "faux") == "faux" else RIGHT
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
                  f"lectures={tools.calls.count('read_file')}  | {r.content[:90]!r}", flush=True)
            shutil.rmtree(root)

if MODE == "detail":
    task = os.environ.get("TACHE", "Ajoute des docstrings plus détaillées aux fonctions de stats.py.")
    for i in range(RUNS):
        root = project()
        notes = []
        tools, confirmed = build(root, notes)
        start = time.monotonic()
        result = tools.call("team_task", task=task)
        print(f"\n######## essai {i + 1} : {time.monotonic() - start:.1f} s ok={result.ok} "
              f"écritures={confirmed.count('write_file')} relais={notes}", flush=True)
        print(result.content[:4000], flush=True)
        print("--- stats.py final :\n" + (root / "stats.py").read_text(encoding="utf-8")[:1500])
        shutil.rmtree(root)
