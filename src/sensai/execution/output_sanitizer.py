"""
Sanitizing of what a tool returns before the model reads it.

Part of the tool gateway contract (docs/architecture/tool-contract.md). Tool output is
untrusted: a web page, a RAG document or an external MCP server can carry
characters the user cannot see and the model can read. This module removes
them. It is deterministic and independent of the EV2 guardrails, so it still
protects when EV2 is not plugged in.
"""
from __future__ import annotations

import re
import unicodedata

# Control characters that carry layout, not hidden content.
_KEPT_CONTROLS = frozenset("\n\t")


def _is_invisible(char: str) -> bool:
    """True for characters that render as nothing (or disguise other text).

    Category "Cf" (format) covers zero-width spaces and joiners, the BOM, the
    soft hyphen, bidi overrides/isolates and the Unicode "tag" block
    (U+E0000-E007F) used to smuggle whole ASCII instructions invisibly.
    Category "Cc" covers C0/C1 controls. Variation selectors are "Mn" but
    render as nothing and can encode hidden payloads, so they are listed.
    """
    if char in _KEPT_CONTROLS:
        return False
    category = unicodedata.category(char)
    if category in ("Cf", "Cc"):
        return True
    code = ord(char)
    return 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF


def strip_invisible(text: str) -> str:
    """Remove invisible format and control characters, keeping newline and tab.

    Side effect accepted: zero-width joiners are dropped too, so emoji
    sequences fall apart into their parts. Safer than letting them through.
    """
    return "".join(c for c in text if not _is_invisible(c))


# ANSI escape sequences: CSI (cursor moves, colours, erase), OSC (window title,
# hyperlinks, terminated by BEL or ST) and lone two-byte escapes. In a terminal
# they can hide or rewrite text the user thinks they are reading.
_ANSI = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[@-Z\\-_]"  # two-byte escapes
)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences whole.

    Must run before `strip_invisible`: that function deletes the ESC byte alone
    and would leave the rest of the sequence ("[31m") behind as visible text.
    """
    return _ANSI.sub("", text)


def normalize(text: str) -> str:
    """NFKC normalization: fold compatibility forms to their plain equivalents.

    Fullwidth letters, ligatures and similar variants would otherwise slip past
    any pattern written for plain ASCII. It does not fold look-alikes from
    other scripts (a Cyrillic "a" stays Cyrillic).
    """
    return unicodedata.normalize("NFKC", text)


def sanitize(text: str) -> str:
    """All deterministic cleaning, in the only order that is correct.

    ANSI sequences go first (their ESC byte is a control character), then
    normalization, then invisible characters last so that nothing normalization
    produces survives either.
    """
    return strip_invisible(normalize(strip_ansi(text)))


# Heuristic markers of text written to steer the model rather than inform it.
# They are signals, not a defence: a hostile text can always be phrased to avoid
# them, and an honest document can quote them. The gateway logs and flags the
# result; it does not rely on them to block.
_INJECTION_MARKERS: dict[str, re.Pattern[str]] = {
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,40}"
        r"\b(previous|prior|above|earlier|all|any|your)\b.{0,40}"
        r"\b(instructions?|rules?|prompts?|guidelines?)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "role_impersonation": re.compile(
        r"^\s*(system|assistant|developer)\s*:|<\|?\s*(im_start|im_end|system)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # The ReAct loop reads these words; a tool output that forges them is
    # trying to write the agent's next step.
    "forged_react_step": re.compile(
        r"^\s*(Action|Action Input|Observation|Final Answer)\s*:", re.MULTILINE
    ),
    "forged_tool_markup": re.compile(
        r"<\s*/?\s*(tool_call|tool_use|function_call|tool_output)\b", re.IGNORECASE
    ),
    "reveal_prompt": re.compile(
        r"\b(reveal|print|show|repeat|output|leak)\b.{0,30}"
        r"\b(system prompt|your instructions|hidden instructions)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    # A remote image in markdown is fetched by the client with the query string
    # attached: a classic way to leak data without any tool call.
    "remote_image": re.compile(r"!\[[^\]]*\]\(\s*https?://", re.IGNORECASE),
}


def find_injection_markers(text: str) -> list[str]:
    """Names of the heuristics that match `text`. Run it on sanitized text."""
    return [name for name, pattern in _INJECTION_MARKERS.items() if pattern.search(text)]


_FENCE_TAG = re.compile(r"<(\s*/?\s*tool_output)", re.IGNORECASE)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]")


def fence_untrusted(tool_name: str, content: str) -> str:
    """Wrap a tool result in a block that marks it as data, not instructions.

    The agent puts this string in the conversation instead of the raw content.
    Any copy of the fence tag inside the content is defused first, otherwise the
    output could close the block itself and continue as if it were outside it.
    The system prompt must tell the model that nothing inside the block is an
    instruction. `suspicious` is set when the injection heuristics match.
    """
    body = _FENCE_TAG.sub(r"&lt;\1", content)
    name = _SAFE_NAME.sub("_", tool_name)
    suspicious = "true" if find_injection_markers(content) else "false"
    return (
        f'<tool_output tool="{name}" trust="untrusted" suspicious="{suspicious}">\n'
        f"{body}\n"
        "</tool_output>"
    )
