"""
Commande `sensai-schedule` : planifier des tâches de l'agent — feature [X5],
ADR-0016.

    sensai-schedule add resume-quotidien --every 1d --prompt "Résume le journal du jour"
    sensai-schedule list
    sensai-schedule run-due          (à appeler depuis cron ou un timer systemd)
    sensai-schedule history resume-quotidien

Ce module n'appelle PAS `get_settings()` : il lit `sys.argv` pour la CLI
interactive. Il relit `config.json` lui-même, avec les mêmes valeurs par défaut.
"""
from __future__ import annotations

import argparse
import functools
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from sensai.config import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    generation_from_config,
    load_config_file,
    load_prompts,
    max_iterations_from_config,
    num_ctx_from_config,
)
from sensai.core.agent import run_agent_turn
from sensai.core.ollama_client import set_generation_options
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.guardrails import InputRules
from sensai.execution.tool_policy import ToolPreferences
from sensai.knowledge.memory import default_data_dir, ensure_private_dir
from sensai.registry import build_registry
from sensai.scheduling.runner import (
    FAILED_STATUSES,
    Scheduler,
    delete_runs,
    list_runs,
)
from sensai.scheduling.tasks import (
    DEFAULT_TIMEOUT_S,
    TASKS_FILE,
    ScheduleStoreError,
    Task,
    TaskStore,
    format_interval,
    parse_interval,
    utc_now,
    validate_task_id,
)

EXIT_FAILED = 1
EXIT_USAGE = 2  # mauvaise utilisation ou fichier des tâches inutilisable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensai-schedule", description="Tâches planifiées de Sensai (ADR-0016)"
    )
    parser.add_argument("--data-dir", help="Dossier des données (défaut : $SENSAI_HOME, ~/.sensai)")
    parser.add_argument("--model", help="Modèle Ollama (défaut : config.json)")
    parser.add_argument("--host", help="URL de l'API Ollama (défaut : config.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="Ajouter une tâche")
    p.add_argument("id", help="Identifiant : lettres minuscules, chiffres et « - » (40 max)")
    p.add_argument(
        "--every", required=True, help="Intervalle : 30m, 1h, 1d, 7d ou secondes (>= 60)"
    )
    p.add_argument("--prompt", required=True, help="Ce que l'agent doit faire")
    p.add_argument("--tools", help="Outils autorisés, séparés par des virgules (défaut : tous)")
    p.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="Durée maximale en secondes"
    )
    sub.add_parser("list", help="Lister les tâches")
    p = sub.add_parser("remove", help="Supprimer une tâche et ses comptes rendus")
    p.add_argument("id")
    p = sub.add_parser("enable", help="Réactiver une tâche")
    p.add_argument("id")
    p = sub.add_parser("disable", help="Suspendre une tâche sans la supprimer")
    p.add_argument("id")
    p = sub.add_parser("run-due", help="Jouer les tâches échues, puis s'arrêter")
    p.add_argument("--dry-run", action="store_true", help="Lister sans rien lancer")
    p = sub.add_parser("run", help="Jouer une tâche maintenant, échue ou non")
    p.add_argument("id")
    p = sub.add_parser("history", help="Derniers comptes rendus d'une tâche")
    p.add_argument("id")
    p.add_argument("-n", type=int, default=10, help="Nombre de comptes rendus (défaut : 10)")
    p = sub.add_parser("loop", help="Appeler run-due en boucle (sans cron ni systemd)")
    p.add_argument("--every", default="300", help="Pause entre deux passes (défaut : 300 s)")
    return parser


def _error(message: str) -> None:
    print(f"[Erreur] {message}", file=sys.stderr)


def _paths(args: argparse.Namespace, file_config: dict) -> tuple[Path, TaskStore]:
    raw = args.data_dir or file_config.get("data_dir")
    data_dir = Path(raw).expanduser() if raw else default_data_dir()
    base_dir = data_dir / "schedule"
    return base_dir, TaskStore(base_dir / TASKS_FILE)


def _prepare(base_dir: Path) -> None:
    ensure_private_dir(base_dir.parent)
    ensure_private_dir(base_dir)


def _make_scheduler(
    args: argparse.Namespace, file_config: dict, base_dir: Path, store: TaskStore
) -> Scheduler:
    system_prompt, _, _ = load_prompts(
        file_config.get("system_prompt_path"), file_config.get("memory_prompt_path")
    )
    preferences = ToolPreferences.from_dict(file_config.get("tools", {}))
    permissions = FilePermissions.from_dict(file_config.get("files"))
    # M2, ADR-0045 : sans num_ctx, une tâche planifiée resterait soumise à la
    # troncature par défaut d'Ollama, sans personne pour s'en apercevoir.
    num_ctx = num_ctx_from_config(file_config)
    # Paramètres de génération et nombre d'étapes (ADR-0057), comme le CLI.
    set_generation_options(generation_from_config(file_config))
    max_iterations = max_iterations_from_config(file_config)
    return Scheduler(
        store,
        base_dir,
        host=args.host or file_config.get("host", DEFAULT_HOST),
        model=args.model or file_config.get("model", DEFAULT_MODEL),
        system_prompt=system_prompt,
        agent=functools.partial(run_agent_turn, num_ctx=num_ctx, max_iterations=max_iterations),
        # Mêmes règles de refus que le CLI et le web (EV2, ADR-0027).
        input_rules=InputRules.from_config(file_config.get("input_blocklist")),
        registry=build_registry(permissions),
        preferences=preferences,
    )


def _print_records(records: list[dict]) -> None:
    for record in records:
        suffix = f" — {record['error']}" if record.get("error") else ""
        print(f"{record['task_id']} : {record['status']}{suffix}")


def _failed(records: list[dict]) -> bool:
    return any(r["status"] in FAILED_STATUSES for r in records)


def _next_due(task: Task) -> str:
    if not task.enabled:
        return "-"
    due = task.next_due()
    if due is None or due <= utc_now():
        return "maintenant"
    return due.astimezone().strftime("%Y-%m-%d %H:%M")


def _cmd_add(args: argparse.Namespace, store: TaskStore, base_dir: Path) -> int:
    try:
        validate_task_id(args.id)
        interval = parse_interval(args.every)
    except ValueError as exc:
        _error(str(exc))
        return EXIT_USAGE
    if not args.prompt.strip():
        _error("Le prompt est vide.")
        return EXIT_USAGE
    if args.timeout <= 0:
        _error("--timeout doit être un nombre de secondes positif.")
        return EXIT_USAGE
    tools = None
    if args.tools is not None:
        tools = [t.strip() for t in args.tools.split(",") if t.strip()]
        known = {d["name"] for d in build_registry().describe_all()}
        unknown = [t for t in tools if t not in known]
        if unknown:
            _error(
                f"Outil(s) inconnu(s) : {', '.join(unknown)}. "
                f"Outils disponibles : {', '.join(sorted(known)) or 'aucun'}."
            )
            return EXIT_USAGE
    _prepare(base_dir)
    try:
        store.add(
            Task(id=args.id, prompt=args.prompt, interval_s=interval, tools=tools,
                 timeout_s=args.timeout)
        )
    except ValueError as exc:
        _error(str(exc))
        return EXIT_FAILED
    print(f"Tâche « {args.id} » ajoutée (toutes les {format_interval(interval)}).")
    return 0


def _cmd_list(store: TaskStore) -> int:
    tasks = store.load()
    if not tasks:
        print("Aucune tâche planifiée.")
        return 0
    print(f"{'ID':<40}  {'INTERVALLE':<10}  {'ACTIVE':<6}  {'DERNIÈRE EXÉCUTION':<25}  "
          f"{'STATUT':<14}  PROCHAINE")
    for t in tasks:
        print(
            f"{t.id:<40}  {format_interval(t.interval_s):<10}  {'oui' if t.enabled else 'non':<6}  "
            f"{(t.last_run_at or '-')[:19]:<25}  {t.last_status or '-':<14}  {_next_due(t)}"
        )
    return 0


def _cmd_history(args: argparse.Namespace, store: TaskStore, base_dir: Path) -> int:
    records = list_runs(base_dir, args.id)
    if not records and store.get(args.id) is None:
        _error(f"Tâche inconnue : {args.id}")
        return EXIT_FAILED
    if not records:
        print("Aucune exécution pour l'instant.")
        return 0
    for record in records[: max(args.n, 0)]:
        calls = record.get("tool_calls", [])
        refused = sum(1 for c in calls if not c.get("ok"))
        detail = record.get("error") or " ".join((record.get("answer") or "").split())[:80]
        print(
            f"{record['started_at'][:19]}  {record['status']:<14}  "
            f"outils : {len(calls)} ({refused} en échec)  {detail}"
        )
    return 0


def run(args: argparse.Namespace) -> int:
    file_config = load_config_file()
    base_dir, store = _paths(args, file_config)

    if args.command in ("history", "remove", "enable", "disable", "run"):
        # Avant tout accès disque : l'identifiant sert à fabriquer des chemins.
        try:
            validate_task_id(args.id)
        except ValueError as exc:
            _error(str(exc))
            return EXIT_USAGE

    if args.command == "add":
        return _cmd_add(args, store, base_dir)
    if args.command == "list":
        return _cmd_list(store)
    if args.command == "history":
        return _cmd_history(args, store, base_dir)
    if args.command == "remove":
        if not store.remove(args.id):
            _error(f"Tâche inconnue : {args.id}")
            return EXIT_FAILED
        delete_runs(base_dir, args.id)
        print(f"Tâche « {args.id} » supprimée, ainsi que ses comptes rendus.")
        return 0
    if args.command in ("enable", "disable"):
        if not store.update(args.id, enabled=args.command == "enable"):
            _error(f"Tâche inconnue : {args.id}")
            return EXIT_FAILED
        print(f"Tâche « {args.id} » {'activée' if args.command == 'enable' else 'suspendue'}.")
        return 0

    # Les commandes qui jouent des tâches : run-due, run, loop.
    if args.command == "loop":
        try:
            every = parse_interval(args.every)
        except ValueError as exc:
            _error(str(exc))
            return EXIT_USAGE
    if args.command == "run-due" and args.dry_run:
        due = [t for t in store.load() if t.is_due(utc_now())]
        print("\n".join(t.id for t in due) if due else "Aucune tâche échue.")
        return 0
    _prepare(base_dir)
    scheduler = _make_scheduler(args, file_config, base_dir, store)
    if args.command == "run-due":
        records = scheduler.run_due()
        if not records:
            print("Aucune tâche échue.")
        _print_records(records)
        return EXIT_FAILED if _failed(records) else 0
    if args.command == "run":
        task = store.get(args.id)
        if task is None:
            _error(f"Tâche inconnue : {args.id}")
            return EXIT_FAILED
        record = scheduler.run_task(task)
        _print_records([record])
        return EXIT_FAILED if record["status"] in FAILED_STATUSES else 0
    if args.command == "loop":
        print(f"Boucle : une passe toutes les {every} s (Ctrl+C pour arrêter).")
        try:
            scheduler.loop(every)
        except KeyboardInterrupt:
            print("\nArrêt.")
        return 0
    return EXIT_USAGE  # inatteignable : argparse impose une commande connue


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        return run(args)
    except ScheduleStoreError as exc:
        _error(
            f"Fichier des tâches inutilisable, il n'a pas été modifié : {exc}\n"
            "Corrigez-le à la main ou déplacez-le pour repartir de zéro."
        )
        return EXIT_USAGE
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        # Configuration illisible (config.json, clé « tools »), dossier non inscriptible...
        _error(f"Configuration ou fichiers inutilisables : {exc}")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
