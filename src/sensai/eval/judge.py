"""
The LLM judge - feature [EV1], ADR-0019.

One model call per case, which answers in JSON:

    {"relevance": 1-5, "coherence": 1-5,
     "claims": [{"text", "verdict", "sources": ["S1"], "explanation"}]}

Faithfulness is not asked of the model: it is computed here from the verdicts
(SUPPORTED / number of claims). A local model sometimes outputs broken JSON;
we retry with a corrective message, and if that is not enough the case is
marked `judge_error` - never scored 0, never counted in the averages.

The prompt text comes from the prompt registry (A4, ADR-0010) under the name
`judge`: changing the prompt therefore means a new version, and the report
keeps its fingerprint.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any, NamedTuple

import requests

from sensai.config import PROJECT_ROOT, prompts_dir
from sensai.core.ollama_client import OllamaError
from sensai.eval.sources import Passage, format_passages
from sensai.knowledge.prompt_versions import PromptStore

JUDGE_PROMPT_NAME = "judge"
DEFAULT_TEMPERATURE = 0
DEFAULT_SEED = 42
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT_S = 300
RAW_MAX_CHARS = 2000

SUPPORTED = "SUPPORTED"
CONTRADICTED = "CONTRADICTED"
UNVERIFIABLE = "UNVERIFIABLE"
VERDICTS = (SUPPORTED, CONTRADICTED, UNVERIFIABLE)
FLAG_INVALID_CITATION = "citation_invalide"

JudgeFn = Callable[[list[dict]], str]
AnswerFn = Callable[[str, list[Passage]], str]

_PLACEHOLDER = re.compile(r"\{\{(QUESTION|PASSAGES|ANSWER)\}\}")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class JudgeOutputError(ValueError):
    """The judge's output is unusable (JSON, schema or values)."""


class JudgePrompt(NamedTuple):
    text: str
    version: str
    sha256: str


# --- prompt ----------------------------------------------------------------


def find_judge_store() -> PromptStore:
    """Registry that holds the `judge` prompt.

    The current directory's one if it has it (same rule as `prompts_dir`),
    otherwise the repo's: `sensai-eval` can be run from another project whose
    `prompts/` has no judge.
    """
    store = PromptStore(prompts_dir())
    if store.exists() and JUDGE_PROMPT_NAME in store.names():
        return store
    return PromptStore(PROJECT_ROOT / "prompts")


def load_judge_prompt(store: PromptStore, version: str | None = None) -> JudgePrompt:
    """Text, version number and sha256 of the judge prompt (active by default).

    KeyError if the prompt or the version does not exist.
    """
    version_id = store.resolve(JUDGE_PROMPT_NAME, version) if version else store.active(
        JUDGE_PROMPT_NAME
    )
    text = store.load(JUDGE_PROMPT_NAME, version_id)
    return JudgePrompt(text, version_id, hashlib.sha256(text.encode("utf-8")).hexdigest())


def build_messages(
    prompt: str, question: str, answer: str, passages: list[Passage]
) -> list[dict]:
    """Fills the prompt's three tokens in a single pass.

    No `str.format` (the prompt contains JSON braces) and no chained `replace`
    (a question containing `{{ANSWER}}` would be rewritten).
    """
    values = {
        "QUESTION": question,
        "PASSAGES": format_passages(passages),
        "ANSWER": answer,
    }
    content = _PLACEHOLDER.sub(lambda m: values[m.group(1)], prompt)
    return [{"role": "user", "content": content}]


# --- output parsing ----- ----------------------------------------------------


def _extract_json(raw: str) -> Any:
    text = _FENCE.sub("", raw.strip()).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise JudgeOutputError("no JSON object in the answer")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise JudgeOutputError(f"invalid JSON: {e}") from e


def _score(data: dict, key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise JudgeOutputError(f"\"{key}\" must be an integer from 1 to 5 (got: {value!r})")
    return value


def _claim(raw: Any, index: int, passage_ids: set[str]) -> dict:
    where = f"claims[{index}]"
    if not isinstance(raw, dict):
        raise JudgeOutputError(f"{where} must be an object")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise JudgeOutputError(f"{where}: \"text\" missing")
    verdict = raw.get("verdict")
    verdict = verdict.strip().upper() if isinstance(verdict, str) else verdict
    if verdict not in VERDICTS:
        raise JudgeOutputError(
            f"{where}: unknown verdict {raw.get('verdict')!r} (expected: {', '.join(VERDICTS)})"
        )
    sources = raw.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise JudgeOutputError(f"{where}: \"sources\" must be a list of strings")
    explanation = raw.get("explanation", "")
    if not isinstance(explanation, str):
        raise JudgeOutputError(f"{where}: \"explanation\" must be a string")

    claim: dict[str, Any] = {
        "text": text.strip(),
        "verdict": verdict,
        "sources": sources,
        "explanation": explanation.strip(),
        "flags": [],
    }
    # A verdict that relies on no known passage is not verifiable: we downgrade
    # it instead of trusting it (and keep the original).
    if verdict in (SUPPORTED, CONTRADICTED) and (
        not sources or not all(s in passage_ids for s in sources)
    ):
        claim["verdict"] = UNVERIFIABLE
        claim["verdict_original"] = verdict
        claim["flags"].append(FLAG_INVALID_CITATION)
    return claim


def parse_judgment(raw: str, passage_ids: set[str] | list[str]) -> dict:
    """Validates the judge's output; JudgeOutputError if it is unusable."""
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise JudgeOutputError("the answer must be a JSON object")
    ids = set(passage_ids)
    relevance = _score(data, "relevance")
    coherence = _score(data, "coherence")
    claims = data.get("claims")
    if not isinstance(claims, list):
        raise JudgeOutputError('"claims" must be a list (empty when there is no claim)')
    return {
        "relevance": relevance,
        "coherence": coherence,
        "claims": [_claim(c, i, ids) for i, c in enumerate(claims)],
    }


def faithfulness(claims: list[dict]) -> float | None:
    """Share of SUPPORTED claims; None without claims (nothing to check)."""
    if not claims:
        return None
    return round(sum(c["verdict"] == SUPPORTED for c in claims) / len(claims), 4)


# --- one case ----------------------------------------------------------------


def _corrective_message(error: Exception) -> str:
    return (
        f"Your answer is unusable: {error}. Answer again with only "
        'the requested JSON object ({"relevance", "coherence", "claims"}), '
        "with no surrounding text."
    )


def judge_case(
    question: str,
    answer: str,
    passages: list[Passage],
    judge_fn: JudgeFn,
    prompt: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """Has a case judged. Never raises: a failure becomes `status: judge_error`.

    An unusable output is sent back to the judge (with its own output and a
    corrective message) up to `max_retries` times. An `OllamaError` is not
    retried: if the server is down, three more calls change nothing.
    """
    messages = build_messages(prompt, question, answer, passages)
    by_id = {p.id: p for p in passages}
    attempts = 0
    raw = ""
    error: Exception | None = None
    while attempts <= max_retries:
        attempts += 1
        try:
            raw = judge_fn(list(messages))
        except OllamaError as e:
            return _failure(f"Ollama: {e}", raw, attempts)
        try:
            judgment = parse_judgment(raw, set(by_id))
        except JudgeOutputError as e:
            error = e
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": _corrective_message(e)},
            ]
            continue
        return _success(judgment, by_id, attempts)
    return _failure(str(error), raw, attempts)


def _success(judgment: dict, by_id: dict[str, Passage], attempts: int) -> dict:
    claims = judgment["claims"]
    for claim in claims:
        claim["citations"] = [by_id[s].citation() for s in claim["sources"] if s in by_id]
    return {
        "status": "ok",
        "scores": {
            "relevance": judgment["relevance"],
            "coherence": judgment["coherence"],
            "faithfulness": faithfulness(claims),
        },
        "claims": claims,
        "flagged": [c for c in claims if c["verdict"] != SUPPORTED],
        "attempts": attempts,
    }


def _failure(error: str, raw: str, attempts: int) -> dict:
    return {
        "status": "judge_error",
        "error": error,
        "raw": raw[:RAW_MAX_CHARS],
        "attempts": attempts,
    }


# --- the real judge -----------------------------------------------------------


def ollama_judge(
    host: str,
    model: str,
    temperature: float = DEFAULT_TEMPERATURE,
    seed: int = DEFAULT_SEED,
    timeout: float = DEFAULT_TIMEOUT_S,
    num_ctx: int | None = None,
) -> JudgeFn:
    """Real judge: `POST /api/chat`, no streaming, JSON output, temperature 0.

    `num_ctx` (M2, ADR-0045): the judge prompt pastes the answer and its
    passages; without it, Ollama may silently truncate them and the score
    would judge a cut-off text.

    `stream_chat` takes no `options` and streams; a judge needs the whole
    text, a reproducible output (fixed seed) and Ollama's JSON mode. We do not
    touch `ollama_client.py` (ADR-0019).
    """
    url = f"{host.rstrip('/')}/api/chat"
    options: dict[str, float | int] = {"temperature": temperature, "seed": seed}
    if num_ctx:
        options["num_ctx"] = num_ctx

    def judge(messages: list[dict]) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": options,
        }
        response = None
        try:
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()["message"]["content"]
        except requests.exceptions.ConnectionError as e:
            raise OllamaError(
                f"Cannot reach Ollama at {host}. "
                "Check that `ollama serve` is running."
            ) from e
        except requests.exceptions.Timeout as e:
            raise OllamaError(f"The judge is not responding ({timeout:g} s timeout).") from e
        except requests.exceptions.HTTPError as e:
            detail = response.text[:200] if response is not None else str(e)
            raise OllamaError(f"Ollama error: {detail}") from e
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            raise OllamaError(f"Unexpected Ollama response: {e}") from e

    return judge
