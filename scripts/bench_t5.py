"""
Mesures de T5 (sortie structurée, ADR-0039) : la réponse JSON est-elle fondée
sur le projet ? Compare l'appel direct (sans outils, ADR-0036) et l'appel en
deux temps (l'agent cherche avec ses outils, puis mise en forme par schéma),
sur des questions dont la bonne réponse est connue. Projet jetable (dossier
temporaire). Résultats : docs/performance/T5-structured.md.

    python scripts/bench_t5.py <hôte Ollama> [essais]
"""
# ruff: noqa: E402, E501  (chemin d'import ajouté avant les imports ; jeux sur une ligne)
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sensai.core.agent import run_agent_turn
from sensai.core.events import Token
from sensai.core.structured import grounded_prompt, run_structured_query
from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.gateway import ToolGateway
from sensai.tools.read_file_tool import ReadFileTool

HOST = sys.argv[1]
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
MODEL = "qwen3-coder:30b"
SYSTEM = (ROOT / "prompts" / "system" / "v2.txt").read_text(encoding="utf-8")

FILES = {
    "stats.py": "def maximum(valeurs):\n    plus_grand = valeurs[0]\n    for v in valeurs:\n        if v > plus_grand:\n            plus_grand = v\n    return plus_grand\n",
    "texte.py": 'def compter_mots(phrase):\n    return len(phrase.split())\n\n\ndef inverser(phrase):\n    return phrase[::-1]\n',
    "reglages.py": "DEBUG = False\nPORT = 8042\n",
}
LIST = {"type": "object", "properties": {"fonctions": {"type": "array", "items": {"type": "string"}}}, "required": ["fonctions"]}
PORT = {"type": "object", "properties": {"port": {"type": "integer"}}, "required": ["port"]}


def names(r):
    """Les noms de fonctions, sans signature : « inverser(phrase) » compte comme « inverser »."""
    return sorted(str(f).split("(")[0].strip() for f in r.get("fonctions", []))


# (demande, schéma, vérification de la réponse)
CASES = [
    ("Donne la liste des fonctions définies dans stats.py.", LIST, lambda r: names(r) == ["maximum"]),
    ("Donne la liste des fonctions définies dans texte.py.", LIST, lambda r: names(r) == ["compter_mots", "inverser"]),
    ("Quel port est configuré dans reglages.py ?", PORT, lambda r: r.get("port") == 8042),
]

root = Path(tempfile.mkdtemp(prefix="sensai-t5-"))
for name, content in FILES.items():
    (root / name).write_text(content, encoding="utf-8")
registry = ToolRegistry()
gateway = ToolGateway(registry, None, confirm=lambda request: True)
registry.register(ReadFileTool(FilePermissions.for_workspace(root)))


def gather(question):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    return "".join(e.text for e in run_agent_turn(HOST, MODEL, messages, gateway) if isinstance(e, Token))


for mode in ("direct", "deux temps"):
    ok_total = 0
    for question, schema, check in CASES:
        ok, times, sample = 0, [], None
        for _ in range(RUNS):
            start = time.monotonic()
            found = "" if mode == "direct" else gather(question)
            prompt = question if mode == "direct" else grounded_prompt(question, found)
            result = run_structured_query(HOST, MODEL, prompt, schema)
            times.append(time.monotonic() - start)
            ok += check(result)
            if found and not check(result):
                print(f"   faux ; l'agent avait trouvé : {found[:160]!r}", flush=True)
            sample = result
        ok_total += ok
        print(f"{mode:10} juste {ok}/{RUNS}  {min(times):5.1f} à {max(times):5.1f} s  | {question[:45]}  ex. {json.dumps(sample, ensure_ascii=False)[:80]}", flush=True)
    print(f"==> {mode} : {ok_total}/{RUNS * len(CASES)} réponses justes", flush=True)
