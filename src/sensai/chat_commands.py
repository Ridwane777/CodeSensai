"""
Commandes `/schedule` et `/eval` du chat — features [X5] et [EV1], ADR-0028.

Ce sont les mêmes commandes que `sensai-schedule` et `sensai-eval`, tapées sans
quitter la conversation. Le module ne réimplémente rien : il découpe la ligne,
ajoute le dossier de données, l'hôte et le modèle de la session, puis appelle
le `main` de chaque outil. Une seule source de vérité pour les options et les
codes de sortie.

Seule une ligne tapée par l'utilisateur arrive ici (la boucle du CLI lit le
clavier) ; ce que le modèle écrit n'est jamais interprété comme une commande.
"""
from __future__ import annotations

import shlex
from collections.abc import Callable, Sequence

from sensai.eval.cli import main as eval_main
from sensai.schedule_cli import main as schedule_main

COMMANDS = ("/schedule", "/eval")

USAGE = {
    "/schedule": (
        "Usage : /schedule add <id> --every 1d --prompt \"…\" | list | run <id> | run-due"
        " | history <id> | enable|disable|remove <id>"
    ),
    "/eval": (
        "Usage : /eval run --dataset <fichier.jsonl> --out <rapport.json>"
        " | compare <rapport_a> <rapport_b>"
    ),
}

# `loop` ne rend jamais la main : il figerait le chat. À lancer dans un autre terminal.
_FORBIDDEN = {"/schedule": {"loop"}}


def is_chat_command(line: str) -> bool:
    """Vrai si la ligne *commence* par une de ces commandes.

    « pourquoi /eval échoue ? » est une question pour le modèle, pas une commande.
    """
    parts = line.split(None, 1)
    return bool(parts) and parts[0] in COMMANDS


def _with_default(argv: list[str], flag: str, value: str | None) -> list[str]:
    """Ajoute `flag value` sauf si l'utilisateur l'a donné lui-même."""
    if value and flag not in argv:
        return [flag, value, *argv]
    return argv


def run_chat_command(
    line: str,
    *,
    host: str,
    model: str,
    data_dir: str | None,
    output_fn: Callable[[str], None] = print,
    schedule: Callable[[Sequence[str]], int] = schedule_main,
    evaluate: Callable[[Sequence[str]], int] = eval_main,
) -> int:
    """Exécute la ligne et renvoie le code de sortie (0 = succès).

    Ne lève jamais : un argument mal formé ou une panne s'affichent et la
    conversation continue. `schedule` et `evaluate` servent aux tests.
    """
    try:
        words = shlex.split(line)
    except ValueError as exc:  # guillemet non fermé
        output_fn(f"[Erreur] Commande illisible : {exc}")
        return 2
    command, args = words[0], words[1:]

    if not args:
        output_fn(USAGE[command])
        return 2
    if args[0] in _FORBIDDEN.get(command, ()):
        output_fn(
            f"« {command} {args[0]} » ne rend pas la main : lance `sensai-schedule {args[0]}`"
            " dans un autre terminal."
        )
        return 2

    if command == "/schedule":
        # Options globales : avant la sous-commande.
        argv = _with_default(args, "--data-dir", data_dir)
        argv = _with_default(argv, "--host", host)
        argv = _with_default(argv, "--model", model)
        entry = schedule
    else:
        argv = args
        if args[0] == "run":  # `compare` n'appelle aucun modèle
            argv = _with_default(argv, "--host", host)
            argv = _with_default(argv, "--judge-model", model)
        entry = evaluate

    try:
        return entry(argv)
    except SystemExit as exc:  # argparse : option inconnue, --help
        return exc.code if isinstance(exc.code, int) else 2
    except KeyboardInterrupt:
        output_fn("\nInterrompu.")
        return 130
    except Exception as exc:  # un outil en panne ne doit pas fermer le chat
        output_fn(f"[Erreur] {command} a échoué : {exc}")
        return 1
