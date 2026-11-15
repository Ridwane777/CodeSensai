"""
Minimal HTTP client for the Ollama API - NO LLM framework (project constraint).
Everything goes through direct HTTP calls via `requests`.
"""
import json
from collections.abc import Iterator
from typing import Any

import requests


class OllamaError(Exception):
    """Raised when Ollama is unreachable or returns an error."""
    pass


# Generation parameters (ADR-0057) accepted in config.json, `generation`
# section, and sent in `options` on every chat call. Other Ollama options
# remain possible but are not exposed.
GENERATION_KEYS = ("temperature", "top_p", "top_k", "seed", "num_predict", "repeat_penalty")

# Set once at startup (CLI, sensai-web, sensai-schedule): every chat call
# goes through stream_chat_messages, so a single point is enough.
_generation: dict[str, Any] = {}


def set_generation_options(options: dict[str, Any] | None) -> None:
    """Generation parameters added to every call (empty: the model's defaults)."""
    _generation.clear()
    _generation.update({k: v for k, v in (options or {}).items() if v is not None})


def generation_options() -> dict[str, Any]:
    """The parameters in effect (shown by /context)."""
    return dict(_generation)


# HTTP timeouts (connect, read). Read covers the wait for the first chunk: on
# CPU, qwen3:8b reads the system prompt and tools (several thousand tokens) at
# ~10 tokens/s, i.e. several minutes before answering. 60 s made every turn
# fail on the development laptop (docs/performance/trials/trial-2026-11-06.md).
# Connect stays short: a stopped Ollama is reported right away.
CONNECT_TIMEOUT = 10
DEFAULT_REQUEST_TIMEOUT = 600
_timeout = {"read": DEFAULT_REQUEST_TIMEOUT}


def set_request_timeout(seconds: float | None) -> None:
    """Timeout for an Ollama reply, set at startup (None: the default)."""
    _timeout["read"] = seconds or DEFAULT_REQUEST_TIMEOUT


def stream_chat_messages(
    host: str,
    model: str,
    messages: list[dict],
    tools: list[dict[str, Any]] | None = None,
    format: dict[str, Any] | str | None = None,
    options: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Send the history to Ollama and yield, as it streams, the `message` field
    of each chunk: `content`, `thinking` and `tool_calls` depending on what
    the model produces.

    `tools` is passed as is in the field of the same name (ADR-0003): Ollama
    then returns tool calls already structured in `tool_calls`, instead of us
    having to guess them from the text.

    `format` is passed as is in the field of the same name (ADR-0036): a JSON
    schema to constrain the reply to that shape, or `"json"`.

    `options` is passed as is in the field of the same name - notably
    `num_ctx` (M2, ADR-0045): without it, Ollama truncates the history at its
    own default limit (2048 or 4096 depending on the version), silently and
    well before the budget M2 tracks.
    """
    url = f"{host}/api/chat"
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
    if format:
        payload["format"] = format
    # Generation parameters set at startup, then the call's own (num_ctx…),
    # which win: the EV1 judge thus keeps its temperature 0.
    merged = {**_generation, **(options or {})}
    if merged:
        payload["options"] = merged

    try:
        response = requests.post(url, json=payload, stream=True,
                                 timeout=(CONNECT_TIMEOUT, _timeout["read"]))
        response.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise OllamaError(
            f"Cannot reach Ollama at {host}. "
            "Check that `ollama serve` is running."
        ) from e
    except requests.exceptions.Timeout as e:
        raise OllamaError(
            f"Ollama is not responding (timeout of {_timeout['read']:g} s). On CPU, increase "
            "\"request_timeout\" in config.json or --request-timeout."
        ) from e
    except requests.exceptions.HTTPError as e:
        detail = response.text[:200] if response is not None else str(e)
        raise OllamaError(f"Ollama error: {detail}") from e

    for line in response.iter_lines():
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        if chunk.get("error"):
            raise OllamaError(chunk["error"])
        # The last chunk (done=True) still carries a `message`, usually empty:
        # pass it on anyway rather than betting that it is.
        message = chunk.get("message")
        if message:
            yield message
        if chunk.get("done"):
            break


def stream_chat(
    host: str, model: str, messages: list[dict], num_ctx: int | None = None
) -> Iterator[str]:
    """
    Send the conversation history to Ollama and stream the reply chunk by
    chunk (not a single block - a project requirement).

    `num_ctx` (M2, ADR-0045): see `stream_chat_messages`.
    """
    options = {"num_ctx": num_ctx} if num_ctx else None
    for message in stream_chat_messages(host, model, messages, options=options):
        content = message.get("content", "")
        if content:
            yield content
