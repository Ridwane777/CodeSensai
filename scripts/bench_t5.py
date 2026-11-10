"""
T5 measurements (structured output, ADR-0039): is the JSON answer grounded in
the project? Compares the direct call (no tools, ADR-0036) with the two-step
call (the agent searches with its tools, then the schema formats the answer),
on questions whose correct answer is known. Throwaway project (temporary
directory). Results: docs/performance/T5-structured.md.

    python scripts/bench_t5.py <Ollama host> [runs]
"""
# ruff: noqa: E402, E501  (import path added before the imports; one-line datasets)
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
    "stats.py": "def maximum(values):\n    largest = values[0]\n    for v in values:\n        if v > largest:\n            largest = v\n    return largest\n",
    "text.py": 'def count_words(sentence):\n    return len(sentence.split())\n\n\ndef reverse(sentence):\n    return sentence[::-1]\n',
    "settings.py": "DEBUG = False\nPORT = 8042\n",
}
LIST = {"type": "object", "properties": {"functions": {"type": "array", "items": {"type": "string"}}}, "required": ["functions"]}
PORT = {"type": "object", "properties": {"port": {"type": "integer"}}, "required": ["port"]}


def names(r):
    """Function names without signature: "reverse(sentence)" counts as "reverse"."""
    return sorted(str(f).split("(")[0].strip() for f in r.get("functions", []))


# (request, schema, answer check)
CASES = [
    ("List the functions defined in stats.py.", LIST, lambda r: names(r) == ["maximum"]),
    ("List the functions defined in text.py.", LIST, lambda r: names(r) == ["count_words", "reverse"]),
    ("Which port is configured in settings.py?", PORT, lambda r: r.get("port") == 8042),
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


for mode in ("direct", "two-step"):
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
                print(f"   wrong; the agent had found: {found[:160]!r}", flush=True)
            sample = result
        ok_total += ok
        print(f"{mode:10} correct {ok}/{RUNS}  {min(times):5.1f} to {max(times):5.1f} s  | {question[:45]}  e.g. {json.dumps(sample, ensure_ascii=False)[:80]}", flush=True)
    print(f"==> {mode}: {ok_total}/{RUNS * len(CASES)} correct answers", flush=True)
