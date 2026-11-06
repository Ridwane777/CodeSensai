"""Prépare le projet de la démo en direct : la journée de Camille (S0 à S9).

Crée un petit projet git qui tient lieu du « rapport de factures » du scénario
(docs/conception/persona-and-scenario.md) : `stats.py`, dont `moyenne` plante
sur une liste vide, un test, un `deploiement.txt` avec la clé d'exemple de la
documentation AWS (fausse, pour S7), un fichier d'exemples few-shot, et le
`config.json` que Marc écrit à S0 (persona « reviewer », sujet bloqué, serveur
MCP, cache et liens de partage activés pour S8 et S9).

L'adresse d'Ollama n'est pas écrite dans le projet : elle se donne au
lancement (`--host`), comme pour tout pod.

    python scripts/prepare_demo_project.py /tmp/codesensei-demo
    cd /tmp/codesensei-demo
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
    """Moyenne mensuelle des factures d'un client."""
    return sum(notes) / len(notes)


def maximum(notes):
    return max(notes)
'''
TEST_STATS = '''from stats import moyenne


def test_moyenne():
    assert moyenne([10, 20]) == 15
'''
README = """# Rapport de factures

Calcule les indicateurs mensuels des clients (moyenne, maximum).
Lancer les tests : `pytest -q` à la racine.
"""
# Clé d'exemple publiée par la documentation AWS : fausse, faite pour être montrée.
DEPLOIEMENT = """Déploiement du rapport
région : eu-west-3
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
"""
FEWSHOT = {"id": "ex-tests", "question": "Comment lancer les tests de ce projet ?",
           "answer": "Lance `pytest -q` à la racine : il trouve tests/test_stats.py.",
           "sources": [], "notes": "exemple de Marc"}
SCHEMA = {"type": "object",
          "properties": {"fonction": {"type": "string"}, "fichier": {"type": "string"}},
          "required": ["fonction", "fichier"]}


def config() -> dict:
    return {
        "max_iterations": 10,
        "generation": {"temperature": 0.2, "top_p": 0.9},
        # S8 : la question répétée sort du cache ; S9 b : le lien de partage pour Marc.
        "cache": True,
        "share_links": True,
        # Une confirmation laissée 60 s sans réponse vaut refus : sur scène, on parle.
        "tools": {"confirm_timeout_s": 300},
        "fewshot_examples": "fewshot.jsonl",
        "personas": {
            "default": "assistant",
            "profiles": [
                {"id": "assistant", "name": "Sensai", "role": "development assistant",
                 "tone": "neutral and precise", "scope": "the current project"},
                {"id": "reviewer", "name": "Sensai Reviewer", "role": "code reviewer",
                 "tone": "precise", "scope": "reviewing the current project, no changes",
                 "tools": {"disabled": ["write_file", "run_code"]}},
            ],
        },
        "input_blocklist": [
            {"name": "salaires", "pattern": "salaire de \\w+", "why": "RH confidentiel"},
        ],
        # L'outil « maison » de S7 : le serveur MCP de test du dépôt (outils calc_*).
        "mcp_servers": {"entreprise": {"command": sys.executable,
                                       "args": [str(FAKE_MCP), "normal"]}},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", type=Path, help="dossier du projet de démo (créé)")
    parser.add_argument("--force", action="store_true", help="remplacer un dossier existant")
    args = parser.parse_args()

    target: Path = args.target
    if target.exists():
        if not args.force:
            sys.exit(f"{target} existe déjà : --force pour le remplacer")
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
                 "commit", "-qm", "rapport de factures"]):
        subprocess.run(cmd, cwd=target, check=True)
    print(f"Projet de démo prêt : {target}")


if __name__ == "__main__":
    main()
