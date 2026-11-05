"""
Essai réel des outils du lot B à travers la passerelle (T2, T3, T4, A3,
garde-fous), sans modèle : la boucle ReAct (A1) qui laisserait le modèle les
appeler n'existe pas encore. Résultats : docs/performance/essai-2026-10-13.md.

    python scripts/essai_outils.py            # T2, T4, A3, garde-fous
    python scripts/essai_outils.py --web      # + T3 (image sensai-browser requise)

Prérequis : Docker qui répond ; pour --web,
`docker build -t sensai-browser:latest docker/browser`.
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from sensai.core.tools import ToolRegistry
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.gateway import ToolGateway
from sensai.execution.guardrails import check_input, filter_output
from sensai.tools.read_file_tool import ReadFileTool
from sensai.tools.sandbox_tool import SandboxTool
from sensai.tools.web_search_tool import WebSearchTool
from sensai.tools.write_file_tool import WriteFileTool


def main() -> int:
    parser = argparse.ArgumentParser(description="Essai réel des outils du lot B")
    parser.add_argument("--web", action="store_true", help="tester aussi web_search")
    web = parser.parse_args().web

    workspace = Path(tempfile.mkdtemp(prefix="sensai-essai-"))
    # Faux secret, au format d'une clé d'API, pour vérifier le masquage.
    (workspace / "a.txt").write_text("bonjour\nAPI_KEY=sk-abcdef1234567890abcdef\n")
    permissions = FilePermissions.for_workspace(workspace)
    registry = ToolRegistry()
    tools = [SandboxTool(), ReadFileTool(permissions), WriteFileTool(permissions)]
    if web:
        tools.append(WebSearchTool())
    for tool in tools:
        registry.register(tool)

    # Confirmeur scripté (A3) : « oui » sauf quand un essai veut tester un refus.
    answer = {"value": True}

    def confirm(request) -> bool:
        print(f"   [confirmation demandée] -> {'oui' if answer['value'] else 'non'}")
        return answer["value"]

    gateway = ToolGateway(
        registry, confirm=confirm, input_guards=[check_input], output_filters=[filter_output]
    )
    checks: list[tuple[str, bool]] = []

    def run(title: str, expected_ok: bool, name: str, **args) -> str:
        result = gateway.call(name, **args)
        content = str(result.content)
        print(f"== {title}\n   ok={result.ok}\n   " + content[:300].replace("\n", "\n   "))
        checks.append((title, result.ok == expected_ok))
        return content

    try:
        out = run("T2 code simple", True, "run_code", code="print(sum(range(10)))")
        checks.append(("T2 résultat 45", "45" in out))
        out = run("T2 boucle infinie", False, "run_code", code="while True: pass")
        checks.append(("T2 tuée par le timeout", "Timeout" in out))
        run("T2 réseau coupé", False, "run_code",
            code="import urllib.request; urllib.request.urlopen('http://example.com', timeout=3)")
        out = run("T4 lecture dans le projet", True, "read_file", path=str(workspace / "a.txt"))
        checks.append(("garde-fou : secret masqué", "sk-abcdef" not in out))
        run("T4 lecture hors projet", False, "read_file", path="/etc/passwd")
        run("T4 écriture confirmée", True, "write_file",
            path=str(workspace / "b.txt"), content="nouveau\n")
        checks.append(("T4 b.txt créé", (workspace / "b.txt").exists()))
        answer["value"] = False
        run("A3 écrasement refusé", False, "write_file",
            path=str(workspace / "a.txt"), content="écrasé\n")
        checks.append(("A3 a.txt intact", (workspace / "a.txt").read_text().startswith("bonjour")))
        if web:
            answer["value"] = True
            run("T3 recherche web", True, "web_search", query="Ollama tool calling API")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    print("\nBilan :")
    for title, passed in checks:
        print(f"  {'✅' if passed else '❌'} {title}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
