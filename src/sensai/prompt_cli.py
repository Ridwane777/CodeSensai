"""
Commande `sensai-prompt` : gérer les versions des prompts — feature [A4],
ADR-0010.

Outil d'équipe, utilisé dans le terminal comme `git` : il n'a besoin ni
d'Ollama ni de l'agent. Déroulé type :

    sensai-prompt show system > brouillon.txt
    sensai --system-prompt brouillon.txt                  (essai)
    sensai-prompt save system brouillon.txt "précise X"   (devient vN)
    sensai-prompt diff system v2 v3
    sensai-prompt use system v3                           (l'agent lit la v3)
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
    """Le nom git de l'auteur, sinon le nom du compte système."""
    try:
        name = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        name = ""
    return name or getpass.getuser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensai-prompt", description="Versions des prompts de Sensai (ADR-0010)"
    )
    parser.add_argument("--dir", help="Dossier des prompts (défaut : prompts/ du dépôt)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("history", help="Lister les versions d'un prompt")
    p.add_argument("prompt")
    p = sub.add_parser("show", help="Afficher une version (l'active par défaut)")
    p.add_argument("prompt")
    p.add_argument("version", nargs="?")
    p = sub.add_parser("diff", help="Comparer deux versions (la 2e = l'active par défaut)")
    p.add_argument("prompt")
    p.add_argument("old")
    p.add_argument("new", nargs="?")
    p = sub.add_parser("save", help="Ranger un fichier comme nouvelle version")
    p.add_argument("prompt")
    p.add_argument("file")
    p.add_argument("description")
    p = sub.add_parser("use", help="Mettre une version en service (déplace le marque-page)")
    p.add_argument("prompt")
    p.add_argument("version")
    sub.add_parser("check", help="Vérifier la cohérence du registre")
    return parser


def run(args: argparse.Namespace, store: PromptStore) -> int:
    if args.command == "history":
        for v in store.history(args.prompt):
            mark = "  (active)" if v["active"] else ""
            print(f"{v['id']:>4}  {v['date']}  {v['author']:<16}  {v['description']}{mark}")
    elif args.command == "show":
        print(store.load(args.prompt, args.version))
    elif args.command == "diff":
        print(store.diff(args.prompt, args.old, args.new) or "(aucune différence)", end="")
    elif args.command == "save":
        path = Path(args.file)
        if not path.is_file():
            print(f"[Erreur] fichier introuvable : {args.file}", file=sys.stderr)
            return 1
        text = path.read_text(encoding="utf-8")
        version = store.save(args.prompt, text, args.description, author=git_author())
        active = store.active(args.prompt)
        if version == active:
            print(f"{args.prompt} {version} rangée et active.")
        else:
            print(f"{args.prompt} {version} rangée (active : {active}). "
                  f"Pour la mettre en service : sensai-prompt use {args.prompt} {version}")
    elif args.command == "use":
        version = store.use(args.prompt, args.version)
        print(f"{args.prompt} : {version} active — utilisée au prochain lancement de sensai. "
              "Commitez prompts/versions.json pour l'appliquer à l'équipe.")
    elif args.command == "check":
        problems = store.check()
        for p in problems:
            print(f"[Erreur] {p}", file=sys.stderr)
        if problems:
            return 1
        print("Registre cohérent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = PromptStore(Path(args.dir) if args.dir else prompts_dir())
    try:
        return run(args, store)
    except KeyError as e:
        print(f"[Erreur] {e.args[0]}", file=sys.stderr)
    except ValueError as e:
        print(f"[Erreur] {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
