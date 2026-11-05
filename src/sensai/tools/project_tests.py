"""
Les tests du projet comme verdict de la chaîne d'équipe (ADR-0056, point 3).

Mesuré sur le pod : un relecteur qui est un modèle validait un travail faux
6 fois sur 6 tant qu'il ne recevait pas le contenu écrit (retrospective,
section 9). Quand le projet a des tests, c'est eux qui décident : ils ne se
laissent pas convaincre par le compte rendu du développeur.

Les tests tournent sur la machine, dans le dossier du projet, pas dans la
sandbox : l'image de la sandbox n'a ni le projet ni ses dépendances. C'est
pourquoi `team_task` est une action à risque « execute » que l'utilisateur
autorise avant tout (ToolGateway).
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

TIMEOUT_S = 120
# La fin de la sortie suffit au développeur : le résumé et les premiers échecs.
OUTPUT_TAIL = 3000

TestRunner = Callable[[], tuple[bool, str]]

# Posée pour le pytest lancé ici : si les tests du projet lancent eux-mêmes une
# équipe CodeSensei (c'est le cas de la suite de ce dépôt), celle-ci ne relance pas
# les tests, sinon chaque niveau en relancerait un autre, sans fin (vu le 2026-11-02).
NO_PROJECT_TESTS = "SENSAI_NO_PROJECT_TESTS"


def has_tests(project: Path) -> bool:
    """Un dossier `tests/` ou des fichiers `test_*.py` à la racine du projet."""
    return (project / "tests").is_dir() or any(project.glob("test_*.py"))


def project_test_runner(project: str | Path, timeout_s: float = TIMEOUT_S) -> TestRunner | None:
    """Une fonction qui lance `pytest -q -x` dans le projet, ou None sans tests."""
    root = Path(project)
    if os.environ.get(NO_PROJECT_TESTS) or not has_tests(root):
        return None

    def run() -> tuple[bool, str]:
        try:
            done = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
                cwd=root, capture_output=True, text=True, timeout=timeout_s,
                env={**os.environ, NO_PROJECT_TESTS: "1"},
            )
        except subprocess.TimeoutExpired:
            return False, f"les tests n'ont pas fini en {timeout_s:.0f} s"
        except OSError as e:
            return False, f"impossible de lancer les tests : {e}"
        output = (done.stdout + done.stderr).strip()
        return done.returncode == 0, output[-OUTPUT_TAIL:]

    return run
