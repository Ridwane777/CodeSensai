"""Prepares the live demo project: Camille's day (S0 to S9).

Creates a small git project that stands in for the scenario's "invoice report"
(docs/design/persona-and-scenario.md): `stats.py`, whose `moyenne` crashes on
an empty list, a test, a `deploiement.txt` with the AWS documentation example
key (fake, for S7), a few-shot examples file, and the `config.json` Marc
writes at S0 ("reviewer" persona, blocked topic, MCP server, cache and share
links enabled for S8 and S9).

The demo project keeps its French identifiers and file names (`moyenne`,
`deploiement.txt`): the recorded demo videos and docs/demo/README.md use them.

The Ollama address is not written into the project: it is given at startup
(`--host`), as for any pod.

    python scripts/prepare_demo_project.py /tmp/codesensai-demo
    cd /tmp/codesensai-demo
    sensai-web --host <Ollama> --model qwen3-coder:30b
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAKE_MCP = REPO / "tests" / "tools" / "fake_mcp_server.py"

STATS = '''def moyenne(notes):
    """Monthly average of a customer's invoices."""
    return sum(notes) / len(notes)


def maximum(notes):
    return max(notes)
'''
TEST_STATS = '''from stats import moyenne


def test_moyenne():
    assert moyenne([10, 20]) == 15
'''
README = """# Invoice report

Computes monthly customer metrics (average, maximum).
Run the tests: `pytest -q` at the root.
"""
# Example key published in the AWS documentation: fake, meant to be shown.
DEPLOIEMENT = """Report deployment
region: eu-west-3
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
"""
FEWSHOT = {"id": "ex-tests", "question": "How do I run this project's tests?",
           "answer": "Run `pytest -q` at the root: it finds tests/test_stats.py.",
           "sources": [], "notes": "Marc's example"}
SCHEMA = {"type": "object",
          "properties": {"function": {"type": "string"}, "file": {"type": "string"}},
          "required": ["function", "file"]}


def config() -> dict:
    return {
        "max_iterations": 10,
        "generation": {"temperature": 0.2, "top_p": 0.9},
        # S8: the repeated question comes from the cache; S9 b: the share link for Marc.
        "cache": True,
        "share_links": True,
        # A confirmation left unanswered for 60 s counts as a refusal: on stage, we talk.
        "tools": {"confirm_timeout_s": 300},
        "fewshot_examples": "fewshot.jsonl",
        "personas": {
            "default": "assistant",
            "profiles": [
                {"id": "assistant", "name": "CodeSensai", "role": "development assistant",
                 "tone": "neutral and precise", "scope": "the current project"},
                {"id": "reviewer", "name": "CodeSensai Reviewer", "role": "code reviewer",
                 "tone": "precise", "scope": "reviewing the current project, no changes",
                 "tools": {"disabled": ["write_file", "run_code"]}},
            ],
        },
        "input_blocklist": [
            # Matches the French demo prompt and its English equivalent.
            {"name": "salaries", "pattern": "(salaire de|salary of) \\w+",
             "why": "confidential HR data"},
        ],
        # The in-house tool of S7: the repository test MCP server (calc_* tools).
        "mcp_servers": {"company": {"command": sys.executable,
                                       "args": [str(FAKE_MCP), "normal"]}},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", type=Path, help="demo project directory (created)")
    parser.add_argument("--force", action="store_true", help="replace an existing directory")
    args = parser.parse_args()

    target: Path = args.target
    if target.exists():
        if not args.force:
            sys.exit(f"{target} already exists: use --force to replace it")
        shutil.rmtree(target)
    (target / "tests").mkdir(parents=True)
    files = {
        "stats.py": STATS, "tests/test_stats.py": TEST_STATS, "README.md": README,
        "deploiement.txt": DEPLOIEMENT,
        "fewshot.jsonl": json.dumps(FEWSHOT, ensure_ascii=False) + "\n",
        "schema.json": json.dumps(SCHEMA, indent=2) + "\n",
        "config.json": json.dumps(config(), indent=2, ensure_ascii=False) + "\n",
    }
    for name, text in files.items():
        (target / name).write_text(text, encoding="utf-8")
    for cmd in (["git", "init", "-q"], ["git", "add", "."],
                ["git", "-c", "user.name=demo", "-c", "user.email=demo@local",
                 "commit", "-qm", "invoice report"]):
        subprocess.run(cmd, cwd=target, check=True)
    print(f"Demo project ready: {target}")


if __name__ == "__main__":
    main()
