"""
`sensai-prompt` command: manage prompt versions — feature [A4], ADR-0010.

A team tool, used in the terminal like `git`: it needs neither Ollama nor
the agent. Typical flow:

    sensai-prompt show system > draft.txt
    sensai --system-prompt draft.txt                      (trial run)
    sensai-prompt save system draft.txt "clarify X"       (becomes vN)
    sensai-prompt diff system v2 v3
    sensai-prompt use system v3                           (the agent reads v3)
"""
from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
from pathlib import Path

from sensai.config import prompts_dir
from sensai.knowledge.prompt_versions import PromptStore


def git_author() -> str:
    """The author's git name, otherwise the system account name."""
    try:
        name = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        name = ""
    return name or getpass.getuser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensai-prompt", description="CodeSensai prompt versions (ADR-0010)"
    )
    parser.add_argument("--dir", help="Prompts directory (default: the repo's prompts/)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("history", help="List a prompt's versions")
    p.add_argument("prompt")
    p = sub.add_parser("show", help="Show a version (the active one by default)")
    p.add_argument("prompt")
    p.add_argument("version", nargs="?")
    p = sub.add_parser("diff", help="Compare two versions (the 2nd = the active one by default)")
    p.add_argument("prompt")
    p.add_argument("old")
    p.add_argument("new", nargs="?")
    p = sub.add_parser("save", help="Store a file as a new version")
    p.add_argument("prompt")
    p.add_argument("file")
    p.add_argument("description")
    p = sub.add_parser("use", help="Put a version into service (moves the bookmark)")
    p.add_argument("prompt")
    p.add_argument("version")
    sub.add_parser("check", help="Check the registry's consistency")
    return parser


def run(args: argparse.Namespace, store: PromptStore) -> int:
    if args.command == "history":
        for v in store.history(args.prompt):
            mark = "  (active)" if v["active"] else ""
            print(f"{v['id']:>4}  {v['date']}  {v['author']:<16}  {v['description']}{mark}")
    elif args.command == "show":
        print(store.load(args.prompt, args.version))
    elif args.command == "diff":
        print(store.diff(args.prompt, args.old, args.new) or "(no difference)", end="")
    elif args.command == "save":
        path = Path(args.file)
        if not path.is_file():
            print(f"[Error] file not found: {args.file}", file=sys.stderr)
            return 1
        text = path.read_text(encoding="utf-8")
        version = store.save(args.prompt, text, args.description, author=git_author())
        active = store.active(args.prompt)
        if version == active:
            print(f"{args.prompt} {version} stored and active.")
        else:
            print(f"{args.prompt} {version} stored (active: {active}). "
                  f"To put it into service: sensai-prompt use {args.prompt} {version}")
    elif args.command == "use":
        version = store.use(args.prompt, args.version)
        print(f"{args.prompt}: {version} active — used on the next sensai launch. "
              "Commit prompts/versions.json to apply it to the team.")
    elif args.command == "check":
        problems = store.check()
        for p in problems:
            print(f"[Error] {p}", file=sys.stderr)
        if problems:
            return 1
        print("Registry consistent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = PromptStore(Path(args.dir) if args.dir else prompts_dir())
    try:
        return run(args, store)
    except KeyError as e:
        print(f"[Error] {e.args[0]}", file=sys.stderr)
    except ValueError as e:
        print(f"[Error] {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
