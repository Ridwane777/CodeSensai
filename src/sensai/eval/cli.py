"""
`sensai-eval` command: evaluate the agent's answers with an LLM judge —
feature [EV1], ADR-0019.

    sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out report.json
    sensai-eval run --dataset ... --out ... --generate        (the agent answers itself)
    sensai-eval run --dataset ... --out ... --sources rag     (passages drawn from the R1 index)
    sensai-eval compare report_a.json report_b.json [--strict]

Like `schedule_cli`, this module does NOT call `get_settings()` (which reads
`sys.argv` for the interactive CLI): it rereads `config.json` with the same defaults.

Exit codes: 0 success; 1 `compare --strict` on two non-comparable reports;
2 unusable file or option.
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
    request_timeout_from_config,
)
from sensai.core.ollama_client import (
    OllamaError,
    set_generation_options,
    set_request_timeout,
    stream_chat,
)
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
        description="Evaluate the agent's answers with an LLM judge (ADR-0019)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Judge the answers of a dataset and write a report")
    run.add_argument("--dataset", required=True, help="JSONL file (one question per line)")
    run.add_argument("--out", required=True, help="JSON report to write")
    run.add_argument(
        "--sources",
        choices=("dataset", "rag"),
        default="dataset",
        help="Passage origin: the dataset (default) or the project index (R1)",
    )
    run.add_argument("--judge-model", help="Judge model (default: the config.json model)")
    run.add_argument("--judge-prompt-version", help="`judge` prompt version (default: the active one)")
    run.add_argument("--host", help="Ollama URL (default: config.json)")
    run.add_argument(
        "--generate",
        action="store_true",
        help="Have the agent answer the cases without an answer",
    )

    compare = sub.add_parser("compare", help="Compare two reports (deltas B minus A)")
    compare.add_argument("report_a")
    compare.add_argument("report_b")
    compare.add_argument("--out", help="Write the comparison as JSON")
    compare.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if the two reports are not comparable",
    )
    return parser


def _error(message: str) -> None:
    print(f"sensai-eval: {message}", file=sys.stderr)


def _fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _fmt_delta(delta: dict, digits: int = 2) -> str:
    if delta["delta"] is None:
        return f"{_fmt(delta['a'], digits)} -> {_fmt(delta['b'], digits)}  (delta n/a)"
    change = f"{delta['delta']:+.{digits}f}"
    return f"{_fmt(delta['a'], digits)} -> {_fmt(delta['b'], digits)}  ({change})"


# --- run ----------------------------------------------------------------------


def build_rag_provider(host: str, file_config: dict) -> SourceProvider:
    """Opens the current project's index the way `sensai` does (cli.open_rag_index).

    We reuse its function instead of copying its construction: the evaluation
    then sees exactly the passages the agent would have received. Late import:
    the interactive CLI module is heavy and useless to the other modes.
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
    """Generator: a single turn, system prompt + passages + question.

    This is not the agent's full loop (no tools, no memory): it is the model
    and the system prompt, which is enough to compare two prompts.
    """

    def answer(question: str, passages: list) -> str:
        content = question
        if passages:
            excerpts = format_passages(passages)
            content = f"Project excerpts:\n\n{excerpts}\n\nQuestion: {question}"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})
        return "".join(stream_chat(host, model, messages, num_ctx=num_ctx)).strip()

    return answer


def _print_run_summary(report: dict, out: str) -> None:
    s, judge = report["summary"], report["judge"]
    print(
        f"EV1 evaluation: {s['n_cases']} case(s), {s['n_scored']} judged, "
        f"{s['judge_errors']} judge error(s), {s['skipped']} skipped, "
        f"{s['source_errors'] + s['generation_errors']} passage or generation error(s)."
    )
    print(
        f"Judge: {judge['model']} (prompt {judge['prompt_name']} {judge['prompt_version']}). "
        "These are a model's estimates, not measurements."
    )
    print(f"  mean relevance    : {_fmt(s['mean_relevance'])} / 5")
    print(f"  mean coherence    : {_fmt(s['mean_coherence'])} / 5")
    print(
        f"  mean faithfulness : {_fmt(s['mean_faithfulness'])} "
        f"(over {s['n_faithfulness']} case(s) with claims)"
    )
    print(
        f"  flagged claims: {s['claims_flagged']} of {s['claims_total']} "
        f"(contradicted or unverifiable)"
    )
    for case in report["cases"]:
        if case["status"] != STATUS_OK:
            print(f"  - {case['id']}: {case['status']} — {case.get('error', '')}")
    print(f"Report: {out}")


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
        # M2, ADR-0045: the judge and the generator send the same window as the CLI.
        num_ctx = num_ctx_from_config(file_config)
        # ADR-0057: generated answers (--generate) follow the same parameters as the
        # CLI; the judge keeps its temperature 0 (judge.py).
        set_generation_options(generation_from_config(file_config))
        set_request_timeout(request_timeout_from_config(file_config))
    except ValueError as e:
        _error(str(e))
        return EXIT_USAGE

    try:
        prompt = load_judge_prompt(find_judge_store(), args.judge_prompt_version)
    except KeyError as e:
        _error(f"judge prompt not found: {e.args[0]}")
        return EXIT_USAGE

    source_provider = None
    if args.sources == "rag":
        try:
            source_provider = build_rag_provider(host, file_config)
        except (EmbeddingError, OSError) as e:
            _error(f"project index unusable: {e}")
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
        _error(f"report not written: {e}")
        return EXIT_USAGE
    _print_run_summary(report, args.out)
    return EXIT_OK


# --- compare --------------------------------------------------------------------


def _print_comparison(comparison: dict) -> None:
    a, b = comparison["a"], comparison["b"]
    print(f"A: {a['created_at']}, judge {a['judge_model']} ({a['judge_prompt_version']})")
    print(f"B: {b['created_at']}, judge {b['judge_model']} ({b['judge_prompt_version']})")
    if comparison["comparable"]:
        print("Reports comparable (same judge, same judge prompt, same dataset).")
    else:
        print("WARNING: reports NOT comparable, read the deltas with caution.")
        for warning in comparison["warnings"]:
            print(f"  ! {warning}")
    labels = {
        "mean_relevance": "mean relevance",
        "mean_coherence": "mean coherence",
        "mean_faithfulness": "mean faithfulness",
        "flagged_claim_rate": "flagged claim rate",
        "judge_errors": "judge errors",
    }
    for key, label in labels.items():
        digits = 0 if key == "judge_errors" else 2
        print(f"  {label:<30} {_fmt_delta(comparison['deltas'][key], digits)}")
    for case in comparison["cases"]:
        print(
            f"  case {case['id']}: relevance {_fmt_delta(case['relevance'], 0)} ; "
            f"faithfulness {_fmt_delta(case['faithfulness'])}"
        )
    if comparison["only_in_a"]:
        print(f"  only in A: {', '.join(comparison['only_in_a'])}")
    if comparison["only_in_b"]:
        print(f"  only in B: {', '.join(comparison['only_in_b'])}")


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
            _error(f"comparison not written: {e}")
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
