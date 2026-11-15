"""
Run an evaluation, produce a JSON report from it, compare two reports -
feature [EV1], ADR-0019.

A report keeps everything that can change a score: the judge (model, prompt and
its fingerprint, temperature, seed), the dataset (fingerprint), the origin of
the passages, and the model that generated the answers. `compare_reports`
refuses to present a comparison as valid when these settings differ: it still
computes the deltas, but with `comparable: false` and the reason.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from sensai.core.ollama_client import OllamaError
from sensai.eval.dataset import Case, Dataset
from sensai.eval.judge import (
    DEFAULT_MAX_RETRIES,
    JUDGE_PROMPT_NAME,
    AnswerFn,
    JudgeFn,
    JudgePrompt,
    judge_case,
)
from sensai.eval.sources import Passage, SourceProvider, static_sources
from sensai.knowledge.rag import EmbeddingError

SCHEMA_VERSION = 1
PASSAGE_TEXT_MAX_CHARS = 1000

STATUS_OK = "ok"
STATUS_JUDGE_ERROR = "judge_error"
STATUS_SKIPPED = "skipped"
STATUS_SOURCE_ERROR = "source_error"
STATUS_GENERATION_ERROR = "generation_error"

SOURCES_MODES = ("dataset", "rag")


class ReportError(ValueError):
    """Unreadable report, or one without the expected shape."""


def sensai_version() -> str:
    try:
        return metadata.version("sensai")
    except metadata.PackageNotFoundError:
        return "unknown"


def _passage_record(passage: Passage) -> dict:
    text = passage.text
    if len(text) > PASSAGE_TEXT_MAX_CHARS:
        text = text[:PASSAGE_TEXT_MAX_CHARS] + "…"
    return {**passage.citation(), "text": text}


def _evaluate_case(
    case: Case,
    *,
    judge_fn: JudgeFn,
    prompt: JudgePrompt,
    sources_mode: str,
    source_provider: SourceProvider | None,
    answer_fn: AnswerFn | None,
    max_retries: int,
) -> dict:
    record: dict[str, Any] = {"id": case.id, "question": case.question}
    if case.notes:
        record["notes"] = case.notes

    # Without an answer or a generator, no point querying the index: the case is skipped.
    if case.answer is None and answer_fn is None:
        return {**record, "answer": None, "status": STATUS_SKIPPED,
                "error": "no answer in the dataset and no --generate"}

    try:
        if sources_mode == "rag":
            passages = source_provider(case.question) if source_provider else []
        else:
            passages = static_sources(case.sources)
    except (EmbeddingError, OllamaError) as e:
        return {**record, "answer": case.answer, "status": STATUS_SOURCE_ERROR,
                "error": f"passage search failed: {e}"}
    record["passages"] = [_passage_record(p) for p in passages]

    answer, origin = case.answer, "dataset"
    if answer is None:
        origin = "generated"
        try:
            answer = answer_fn(case.question, passages)  # type: ignore[misc]
        except OllamaError as e:
            return {**record, "answer": None, "answer_origin": origin,
                    "status": STATUS_GENERATION_ERROR, "error": f"generation failed: {e}"}
        if not answer.strip():
            return {**record, "answer": answer, "answer_origin": origin,
                    "status": STATUS_GENERATION_ERROR, "error": "empty generated answer"}
    record.update(answer=answer, answer_origin=origin)

    return {**record, **judge_case(case.question, answer, passages, judge_fn,
                                   prompt.text, max_retries)}


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize(cases: list[dict]) -> dict:
    """Aggregates over judged cases only (`status == "ok"`).

    A failed case is neither scored 0 nor counted in an average: it is
    counted separately, so its absence shows.
    """
    scored = [c for c in cases if c["status"] == STATUS_OK]
    faithful = [c["scores"]["faithfulness"] for c in scored
                if c["scores"]["faithfulness"] is not None]
    claims_total = sum(len(c["claims"]) for c in scored)
    claims_flagged = sum(len(c["flagged"]) for c in scored)
    return {
        "n_cases": len(cases),
        "n_scored": len(scored),
        "judge_errors": sum(c["status"] == STATUS_JUDGE_ERROR for c in cases),
        "skipped": sum(c["status"] == STATUS_SKIPPED for c in cases),
        "source_errors": sum(c["status"] == STATUS_SOURCE_ERROR for c in cases),
        "generation_errors": sum(c["status"] == STATUS_GENERATION_ERROR for c in cases),
        "mean_relevance": _mean([c["scores"]["relevance"] for c in scored]),
        "mean_coherence": _mean([c["scores"]["coherence"] for c in scored]),
        "mean_faithfulness": _mean(faithful),
        "n_faithfulness": len(faithful),
        "claims_total": claims_total,
        "claims_flagged": claims_flagged,
        "flagged_claim_rate": (
            round(claims_flagged / claims_total, 4) if claims_total else None
        ),
    }


def run_eval(
    dataset: Dataset,
    *,
    judge_fn: JudgeFn,
    judge_info: dict,
    prompt: JudgePrompt,
    sources_mode: str = "dataset",
    source_provider: SourceProvider | None = None,
    answer_fn: AnswerFn | None = None,
    generator: dict | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    now: Callable[[], datetime] | None = None,
) -> dict:
    """Judges every case and returns the report (dict ready for `write_json`).

    `judge_info`: the judge's `model`, `host`, `temperature`, `seed`. The rest
    of the metadata (prompt, dataset, version) is derived from the arguments.
    """
    if sources_mode not in SOURCES_MODES:
        raise ValueError(f"unknown sources_mode: {sources_mode} (expected: dataset or rag)")
    created = (now or (lambda: datetime.now(UTC)))()
    cases = [
        _evaluate_case(
            case,
            judge_fn=judge_fn,
            prompt=prompt,
            sources_mode=sources_mode,
            source_provider=source_provider,
            answer_fn=answer_fn,
            max_retries=max_retries,
        )
        for case in dataset.cases
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": created.isoformat(timespec="seconds"),
        "sensai_version": sensai_version(),
        "judge": {
            "model": judge_info["model"],
            "host": judge_info["host"],
            "prompt_name": JUDGE_PROMPT_NAME,
            "prompt_version": prompt.version,
            "prompt_sha256": prompt.sha256,
            "temperature": judge_info["temperature"],
            "seed": judge_info["seed"],
            "max_retries": max_retries,
        },
        "dataset": {
            "path": dataset.path,
            "sha256": dataset.sha256,
            "n_cases": len(dataset.cases),
        },
        "sources_mode": sources_mode,
        "generator": generator,
        "summary": summarize(cases),
        "cases": cases,
    }


# --- files ---------------------------------------------------------------------


def write_json(path: str | Path, data: dict) -> None:
    """Writes the JSON in one go (temporary file then rename)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def load_report(path: str | Path) -> dict:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise ReportError(f"unreadable report: {e}") from e
    except json.JSONDecodeError as e:
        raise ReportError(f"{path} is not valid JSON: {e.msg}") from e
    if (
        not isinstance(report, dict)
        or not isinstance(report.get("summary"), dict)
        or not isinstance(report.get("cases"), list)
    ):
        raise ReportError(f"{path} is not a sensai-eval report (summary or cases missing)")
    return report


# --- comparison ----------------------------------------------------------------


def _delta(a: float | None, b: float | None) -> dict:
    return {"a": a, "b": b, "delta": None if a is None or b is None else round(b - a, 4)}


def _dig(report: dict, *keys: str) -> Any:
    value: Any = report
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


# (key, label): what makes two reports incomparable.
_COMPARABILITY_CHECKS = (
    (("schema_version",), "report format version"),
    (("judge", "model"), "judge model"),
    (("judge", "prompt_sha256"), "judge prompt (sha256 fingerprint)"),
    (("dataset", "sha256"), "dataset (sha256 fingerprint)"),
    (("sources_mode",), "passage origin"),
)

_SUMMARY_METRICS = (
    "mean_relevance", "mean_coherence", "mean_faithfulness", "flagged_claim_rate", "judge_errors",
)


def _case_delta(case_a: dict, case_b: dict) -> dict:
    def score(case: dict, key: str) -> float | None:
        return case["scores"][key] if case["status"] == STATUS_OK else None

    entry: dict[str, Any] = {
        "id": case_a["id"],
        "status_a": case_a["status"],
        "status_b": case_b["status"],
    }
    for key in ("relevance", "coherence", "faithfulness"):
        entry[key] = _delta(score(case_a, key), score(case_b, key))
    entry["flagged"] = _delta(
        len(case_a["flagged"]) if case_a["status"] == STATUS_OK else None,
        len(case_b["flagged"]) if case_b["status"] == STATUS_OK else None,
    )
    return entry


def compare_reports(a: dict, b: dict) -> dict:
    """Deltas `b - a`; `comparable: false` and `warnings` if the settings differ.

    The deltas are always computed (one may want to see them), but
    `comparable: false` means they do not measure only a change in the agent.
    The generator is not in the list: it is what is being compared.
    """
    warnings = []
    for keys, label in _COMPARABILITY_CHECKS:
        va, vb = _dig(a, *keys), _dig(b, *keys)
        if va != vb:
            warnings.append(f"{label} differs: A = {va}, B = {vb}")

    by_id_a = {c["id"]: c for c in a["cases"]}
    by_id_b = {c["id"]: c for c in b["cases"]}
    shared = [i for i in by_id_a if i in by_id_b]

    def header(report: dict) -> dict:
        return {
            "created_at": report.get("created_at"),
            "judge_model": _dig(report, "judge", "model"),
            "judge_prompt_version": _dig(report, "judge", "prompt_version"),
            "generator": report.get("generator"),
        }

    return {
        "comparable": not warnings,
        "warnings": warnings,
        "a": header(a),
        "b": header(b),
        "deltas": {
            key: _delta(a["summary"].get(key), b["summary"].get(key))
            for key in _SUMMARY_METRICS
        },
        "cases": [_case_delta(by_id_a[i], by_id_b[i]) for i in shared],
        "only_in_a": [i for i in by_id_a if i not in by_id_b],
        "only_in_b": [i for i in by_id_b if i not in by_id_a],
    }
