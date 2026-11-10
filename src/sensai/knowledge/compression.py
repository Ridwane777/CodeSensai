"""
[Workstream A — Fresnel] Token budget and rolling-summary compression —
feature [M2], ADR-0045.

Each turn, the token count of what would be sent to the model is estimated
(an approximation, not a real tokenizer — see ADR-0045). Above a budget, the
oldest turns are replaced by a single summary, produced by a separate call to
the chat model (same pattern as `/structured`, `core/structured.py`: one round
trip, no tools) and merged into the system prompt — not added as a second
`user` message, which would break the alternation with the turns kept intact
(PR #97 review).

None of this touches `History.turns` or the saved session (M1, ADR-0007):
only the messages ACTUALLY SENT this turn are compacted. Resuming the session
later restores the full, intact history.
"""
from __future__ import annotations

from sensai.core.ollama_client import OllamaError, stream_chat_messages

CHARS_PER_TOKEN = 4  # rough approximation (English/code); see ADR-0045.
# Context window sent to Ollama (options.num_ctx): without it, Ollama silently
# truncates to its own default (2048 or 4096 depending on the version), long
# before the token budget gets a chance to act. An ESTIMATE (ADR-0045), not a
# measurement: the model actually used may accept more.
DEFAULT_NUM_CTX = 8192
DEFAULT_KEEP_RECENT = 6  # turns (user+assistant) always kept intact
# Margin reserved for the model's answer when the budget is derived from
# num_ctx (ADR-0045): without it, filling all of num_ctx with history leaves
# no room to answer, and Ollama truncates anyway.
RESPONSE_MARGIN_TOKENS = 2000

SUMMARY_PROMPT = (
    "Summarize the following conversation in one compact paragraph, keeping all "
    "important facts, decisions and technical details (file names, values, "
    "errors encountered, decisions made). Do not invent anything, do not "
    "comment on these instructions, return only the summary."
)


class CompressionError(RuntimeError):
    """The summary could not be produced (Ollama unavailable, empty answer…)."""


def count_tokens(text: str) -> int:
    """Rough estimate: ~4 characters per token.

    Not a real tokenizer (ADR-0045, rejected option): good enough to decide
    when to summarize, not for an exact cost measurement.
    """
    return max(1, len(text) // CHARS_PER_TOKEN)


def budget_from_num_ctx(num_ctx: int) -> int:
    """Token budget derived from `num_ctx`, minus an answer margin."""
    return max(1, num_ctx - RESPONSE_MARGIN_TOKENS)


def resolve_budget(max_tokens: int | None, num_ctx: int | None) -> int:
    """The budget to apply: the explicit setting, otherwise derived from `num_ctx`.

    A single place decides the fallback (PR #97 review: two different defaults
    coexisted, 8000 here and 6192 in config.py).
    """
    if max_tokens is not None:
        return max_tokens
    return budget_from_num_ctx(num_ctx or DEFAULT_NUM_CTX)


def count_message_tokens(messages: list[dict]) -> int:
    """Estimated total tokens of `messages` (see `count_tokens`)."""
    return sum(count_tokens(m.get("content", "")) for m in messages)


def exceeds_budget(messages: list[dict], max_tokens: int | None, num_ctx: int | None) -> bool:
    """True if `messages` exceeds the budget. Combined with `compressed == False` after
    `compress_messages`, it means "too big and impossible to reduce": a last
    message inflated by RAG on its own, or fewer turns than `keep_recent`
    (PR #97 review). The caller then warns the user instead of letting Ollama
    truncate silently."""
    return count_message_tokens(messages) > resolve_budget(max_tokens, num_ctx)


def summarize(host: str, model: str, turns: list[dict], num_ctx: int | None = None) -> str:
    """A single model call, without tools, that condenses `turns` into text.

    `turns` is capped to what `num_ctx` can take (minus the answer margin)
    before sending: otherwise, summarizing turns that are themselves too many
    for the model window would be silently truncated by Ollama, exactly the
    problem M2 must avoid (PR #97 review). The oldest turns of `turns` are cut
    first — they lie further back in time than the most recent ones.

    CompressionError if Ollama is unavailable or returns nothing: never an
    empty summary that would silently replace real exchanges.
    """
    transcript = "\n".join(f"{t['role']} : {t['content']}" for t in turns)
    if num_ctx:
        limit_chars = budget_from_num_ctx(num_ctx) * CHARS_PER_TOKEN
        if len(transcript) > limit_chars:
            transcript = "[…beginning truncated, too old to fit in the context…]\n" + \
                transcript[-limit_chars:]
    messages = [
        {"role": "system", "content": SUMMARY_PROMPT},
        {"role": "user", "content": transcript},
    ]
    options = {"num_ctx": num_ctx} if num_ctx else None
    chunks: list[str] = []
    try:
        for message in stream_chat_messages(host, model, messages, options=options):
            if message.get("content"):
                chunks.append(message["content"])
    except OllamaError as e:
        raise CompressionError(str(e)) from e
    summary = "".join(chunks).strip()
    if not summary:
        raise CompressionError("the model returned no summary")
    return summary


def compress_messages(
    host: str,
    model: str,
    messages: list[dict],
    max_tokens: int | None = None,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    num_ctx: int | None = None,
) -> tuple[list[dict], bool]:
    """The messages to SEND this turn; `(messages, compressed)`.

    `messages` is what the caller actually sends to the model — system prompt
    first, THEN everything that accompanies this turn's question (RAG passages,
    few-shot example, etc.: see cli.py, which compresses AFTER adding them, not
    before, otherwise the budget would not count what is really sent — PR #97
    review). If not given, `max_tokens` defaults to the budget derived from
    `num_ctx` (`resolve_budget`). Under that budget, or if there are not enough
    old turns to summarize without breaking the user/assistant alternation,
    `messages` is returned unchanged. `CompressionError` propagates: the caller
    decides whether to continue with the raw turns anyway (see cli.py).

    The summary is merged into the system message, never added as a second
    `user` message: two `user` messages in a row, followed by an `assistant`,
    would break the alternation the API expects.
    """
    max_tokens = resolve_budget(max_tokens, num_ctx)
    system = messages[:1] if messages and messages[0]["role"] == "system" else []
    turns = messages[len(system):]
    if count_message_tokens(messages) <= max_tokens or len(turns) <= keep_recent:
        return messages, False

    # Cut on an even boundary: turns are added in pairs (add_user then
    # add_assistant), so an even index always keeps the right alternation on
    # both sides of the cut.
    cut = len(turns) - keep_recent
    if cut % 2:
        cut -= 1
    if cut < 2:
        return messages, False

    to_summarize, recent = turns[:cut], turns[cut:]
    summary = summarize(host, model, to_summarize, num_ctx=num_ctx)
    note = (
        f"\n\n[Automatic summary of the {len(to_summarize)} previous exchanges, "
        f"generated to stay within the token budget (M2).]\n{summary}"
    )
    base = system[0]["content"] if system else ""
    new_system = [{"role": "system", "content": base + note}]
    return [*new_system, *recent], True
