"""
Real trial run of the Workstream B tools through the gateway (T2, T3, T4, A3,
guardrails), without a model: the ReAct loop (A1) that would let the model call
them did not exist yet. Results: docs/performance/trials/trial-2026-10-13.md.

    python scripts/essai_outils.py            # T2, T4, A3, guardrails
    python scripts/essai_outils.py --web      # + T3 (sensai-browser image required)

Prerequisites: a responding Docker; for --web,
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
    parser = argparse.ArgumentParser(description="Real trial run of the Workstream B tools")
    parser.add_argument("--web", action="store_true", help="also test web_search")
    web = parser.parse_args().web

    workspace = Path(tempfile.mkdtemp(prefix="sensai-trial-"))
    # Fake secret, in API key format, to check masking.
    (workspace / "a.txt").write_text("hello\nAPI_KEY=sk-abcdef1234567890abcdef\n")
    permissions = FilePermissions.for_workspace(workspace)
    registry = ToolRegistry()
    tools = [SandboxTool(), ReadFileTool(permissions), WriteFileTool(permissions)]
    if web:
        tools.append(WebSearchTool())
    for tool in tools:
        registry.register(tool)

    # Scripted confirmer (A3): "yes" unless a trial wants to test a refusal.
    answer = {"value": True}

    def confirm(request) -> bool:
        print(f"   [confirmation requested] -> {'yes' if answer['value'] else 'no'}")
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
        out = run("T2 simple code", True, "run_code", code="print(sum(range(10)))")
        checks.append(("T2 result 45", "45" in out))
        out = run("T2 infinite loop", False, "run_code", code="while True: pass")
        checks.append(("T2 killed by the timeout", "Timeout" in out))
        run("T2 network cut off", False, "run_code",
            code="import urllib.request; urllib.request.urlopen('http://example.com', timeout=3)")
        out = run("T4 read inside the project", True, "read_file", path=str(workspace / "a.txt"))
        checks.append(("guardrail: secret masked", "sk-abcdef" not in out))
        run("T4 read outside the project", False, "read_file", path="/etc/passwd")
        run("T4 confirmed write", True, "write_file",
            path=str(workspace / "b.txt"), content="new\n")
        checks.append(("T4 b.txt created", (workspace / "b.txt").exists()))
        answer["value"] = False
        run("A3 overwrite refused", False, "write_file",
            path=str(workspace / "a.txt"), content="overwritten\n")
        checks.append(("A3 a.txt intact", (workspace / "a.txt").read_text().startswith("hello")))
        if web:
            answer["value"] = True
            run("T3 web search", True, "web_search", query="Ollama tool calling API")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    print("\nSummary:")
    for title, passed in checks:
        print(f"  {'✅' if passed else '❌'} {title}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
