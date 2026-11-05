"""
Commande `sensai-eval` : évaluer les réponses de l'agent avec un juge LLM —
feature [EV1], ADR-0019.

    sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out rapport.json
    sensai-eval run --dataset ... --out ... --generate        (l'agent répond lui-même)
    sensai-eval run --dataset ... --out ... --sources rag     (passages tirés de l'index R1)
    sensai-eval compare rapport_a.json rapport_b.json [--strict]

Comme `schedule_cli`, ce module n'appelle PAS `get_settings()` (qui lit `sys.argv`
pour la CLI interactive) : il relit `config.json` avec les mêmes valeurs par défaut.

Codes de sortie : 0 succès ; 1 `compare --strict` sur deux rapports non comparables ;
2 fichier ou option inutilisable.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sensai.config import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    DEFAULT_RAG_MIN_SCORE,
    DEFAULT_RAG_MODEL,
    DEFAULT_RAG_TOP_K,
    generation_from_config,
    load_config_file,
    load_prompts,
    num_ctx_from_config,
)
from sensai.core.ollama_client import OllamaError, set_generation_options, stream_chat
from sensai.eval.dataset import DatasetError, load_dataset
from sensai.eval.judge import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_SEED,
    DEFAULT_TEMPERATURE,
    AnswerFn,
    find_judge_store,
    load_judge_prompt,
    ollama_judge,
)
from sensai.eval.report import (
    STATUS_OK,
    ReportError,
    compare_reports,
    load_report,
    run_eval,
    write_json,
)
from sensai.eval.sources import SourceProvider, format_passages, rag_sources
from sensai.knowledge.rag import EmbeddingError

EXIT_OK = 0
EXIT_NOT_COMPARABLE = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensai-eval",
        description="Évaluer les réponses de l'agent avec un juge LLM (ADR-0019)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Juger les réponses d'un jeu de données et écrire un rapport")
    run.add_argument("--dataset", required=True, help="Fichier JSONL (une question par ligne)")
    run.add_argument("--out", required=True, help="Rapport JSON à écrire")
    run.add_argument(
        "--sources",
        choices=("dataset", "rag"),
        default="dataset",
        help="Origine des passages : le jeu de données (défaut) ou l'index du projet (R1)",
    )
    run.add_argument("--judge-model", help="Modèle du juge (défaut : le modèle de config.json)")
    run.add_argument("--judge-prompt-version", help="Version du prompt `judge` (défaut : l'active)")
    run.add_argument("--host", help="URL d'Ollama (défaut : config.json)")
    run.add_argument(
        "--generate",
        action="store_true",
        help="Faire répondre l'agent aux cas qui n'ont pas de réponse",
    )

    compare = sub.add_parser("compare", help="Comparer deux rapports (écarts B moins A)")
    compare.add_argument("report_a")
    compare.add_argument("report_b")
    compare.add_argument("--out", help="Écrire la comparaison en JSON")
    compare.add_argument(
        "--strict",
        action="store_true",
        help="Sortir avec le code 1 si les deux rapports ne sont pas comparables",
    )
    return parser


def _error(message: str) -> None:
    print(f"sensai-eval : {message}", file=sys.stderr)


def _fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _fmt_delta(delta: dict, digits: int = 2) -> str:
    if delta["delta"] is None:
        return f"{_fmt(delta['a'], digits)} -> {_fmt(delta['b'], digits)}  (écart n/a)"
    change = f"{delta['delta']:+.{digits}f}"
    return f"{_fmt(delta['a'], digits)} -> {_fmt(delta['b'], digits)}  ({change})"


# --- run ----------------------------------------------------------------------


def build_rag_provider(host: str, file_config: dict) -> SourceProvider:
    """Ouvre l'index du projet courant comme le fait `sensai` (cli.open_rag_index).

    On réutilise sa fonction au lieu de recopier sa construction : l'évaluation
    voit alors exactement les passages que l'agent aurait reçus. Import tardif :
    le module du CLI interactif est lourd et inutile aux autres modes.
    """
    from sensai.cli import open_rag_index
    from sensai.knowledge.memory import default_data_dir

    settings = {"host": host, "rag_model": file_config.get("rag_model", DEFAULT_RAG_MODEL)}
    index = open_rag_index(settings, default_data_dir(), str(Path.cwd().resolve()))
    return rag_sources(
        index,
        top_k=file_config.get("rag_top_k", DEFAULT_RAG_TOP_K),
        min_score=file_config.get("rag_min_score", DEFAULT_RAG_MIN_SCORE),
    )


def make_answer_fn(
    host: str, model: str, system_prompt: str, num_ctx: int | None = None
) -> AnswerFn:
    """Générateur : un seul tour, prompt système + passages + question.

    Ce n'est pas la boucle complète de l'agent (pas d'outils, pas de mémoire) :
    c'est le modèle et le prompt système, ce qui suffit à comparer deux prompts.
    """

    def answer(question: str, passages: list) -> str:
        content = question
        if passages:
            extraits = format_passages(passages)
            content = f"Extraits du projet :\n\n{extraits}\n\nQuestion : {question}"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})
        return "".join(stream_chat(host, model, messages, num_ctx=num_ctx)).strip()

    return answer


def _print_run_summary(report: dict, out: str) -> None:
    s, judge = report["summary"], report["judge"]
    print(
        f"Évaluation EV1 : {s['n_cases']} cas, {s['n_scored']} jugé(s), "
        f"{s['judge_errors']} erreur(s) du juge, {s['skipped']} ignoré(s), "
        f"{s['source_errors'] + s['generation_errors']} erreur(s) de passages ou de génération."
    )
    print(
        f"Juge : {judge['model']} (prompt {judge['prompt_name']} {judge['prompt_version']}). "
        "Ce sont des estimations d'un modèle, pas des mesures."
    )
    print(f"  pertinence moyenne : {_fmt(s['mean_relevance'])} / 5")
    print(f"  cohérence moyenne  : {_fmt(s['mean_coherence'])} / 5")
    print(
        f"  fidélité moyenne   : {_fmt(s['mean_faithfulness'])} "
        f"(sur {s['n_faithfulness']} cas avec affirmations)"
    )
    print(
        f"  affirmations signalées : {s['claims_flagged']} sur {s['claims_total']} "
        f"(contredites ou invérifiables)"
    )
    for case in report["cases"]:
        if case["status"] != STATUS_OK:
            print(f"  - {case['id']} : {case['status']} — {case.get('error', '')}")
    print(f"Rapport : {out}")


def run_command(args: argparse.Namespace) -> int:
    try:
        dataset = load_dataset(args.dataset)
    except DatasetError as e:
        _error(str(e))
        return EXIT_USAGE

    file_config = load_config_file()
    host = args.host or file_config.get("host", DEFAULT_HOST)
    judge_model = args.judge_model or file_config.get("model", DEFAULT_MODEL)
    try:
        # M2, ADR-0045 : le juge et le générateur envoient la même fenêtre que le CLI.
        num_ctx = num_ctx_from_config(file_config)
        # ADR-0057 : les réponses générées (--generate) suivent les mêmes paramètres
        # que le CLI ; le juge garde sa température 0 (judge.py).
        set_generation_options(generation_from_config(file_config))
    except ValueError as e:
        _error(str(e))
        return EXIT_USAGE

    try:
        prompt = load_judge_prompt(find_judge_store(), args.judge_prompt_version)
    except KeyError as e:
        _error(f"prompt du juge introuvable : {e.args[0]}")
        return EXIT_USAGE

    source_provider = None
    if args.sources == "rag":
        try:
            source_provider = build_rag_provider(host, file_config)
        except (EmbeddingError, OSError) as e:
            _error(f"index du projet inutilisable : {e}")
            return EXIT_USAGE

    answer_fn = generator = None
    if args.generate:
        agent_model = file_config.get("model", DEFAULT_MODEL)
        system_prompt, _, versions = load_prompts(file_config.get("system_prompt_path"), None)
        answer_fn = make_answer_fn(host, agent_model, system_prompt, num_ctx=num_ctx)
        generator = {
            "model": agent_model,
            "host": host,
            "system_prompt_version": versions.get("system"),
        }

    report = run_eval(
        dataset,
        judge_fn=ollama_judge(host, judge_model, num_ctx=num_ctx),
        judge_info={
            "model": judge_model,
            "host": host,
            "temperature": DEFAULT_TEMPERATURE,
            "seed": DEFAULT_SEED,
        },
        prompt=prompt,
        sources_mode=args.sources,
        source_provider=source_provider,
        answer_fn=answer_fn,
        generator=generator,
        max_retries=DEFAULT_MAX_RETRIES,
    )
    try:
        write_json(args.out, report)
    except OSError as e:
        _error(f"rapport non écrit : {e}")
        return EXIT_USAGE
    _print_run_summary(report, args.out)
    return EXIT_OK


# --- compare --------------------------------------------------------------------


def _print_comparison(comparison: dict) -> None:
    a, b = comparison["a"], comparison["b"]
    print(f"A : {a['created_at']}, juge {a['judge_model']} ({a['judge_prompt_version']})")
    print(f"B : {b['created_at']}, juge {b['judge_model']} ({b['judge_prompt_version']})")
    if comparison["comparable"]:
        print("Rapports comparables (même juge, même prompt de juge, même jeu de données).")
    else:
        print("ATTENTION : rapports NON comparables, écarts à lire avec prudence.")
        for warning in comparison["warnings"]:
            print(f"  ! {warning}")
    labels = {
        "mean_relevance": "pertinence moyenne",
        "mean_coherence": "cohérence moyenne",
        "mean_faithfulness": "fidélité moyenne",
        "flagged_claim_rate": "part d'affirmations signalées",
        "judge_errors": "erreurs du juge",
    }
    for key, label in labels.items():
        digits = 0 if key == "judge_errors" else 2
        print(f"  {label:<30} {_fmt_delta(comparison['deltas'][key], digits)}")
    for case in comparison["cases"]:
        print(
            f"  cas {case['id']}: pertinence {_fmt_delta(case['relevance'], 0)} ; "
            f"fidélité {_fmt_delta(case['faithfulness'])}"
        )
    if comparison["only_in_a"]:
        print(f"  seulement dans A : {', '.join(comparison['only_in_a'])}")
    if comparison["only_in_b"]:
        print(f"  seulement dans B : {', '.join(comparison['only_in_b'])}")


def compare_command(args: argparse.Namespace) -> int:
    try:
        a, b = load_report(args.report_a), load_report(args.report_b)
    except ReportError as e:
        _error(str(e))
        return EXIT_USAGE
    comparison = compare_reports(a, b)
    _print_comparison(comparison)
    if args.out:
        try:
            write_json(args.out, comparison)
        except OSError as e:
            _error(f"comparaison non écrite : {e}")
            return EXIT_USAGE
    if args.strict and not comparison["comparable"]:
        return EXIT_NOT_COMPARABLE
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return run_command(args)
        return compare_command(args)
    except OllamaError as e:
        _error(str(e))
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
