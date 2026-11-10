"""
The text of a turn's reply, as it is stored (M1 session, A6 cache).

The model sometimes writes a bit of text, calls a tool, then writes the rest —
or even rewrites the same reply. Concatenated as is, these chunks produced
"…the file.The file…" in the stored session (real trial run on 2026-11-01).
Here, each chunk separated by a tool call becomes a paragraph, and a chunk the
model rewrites later is dropped, whether identical or rephrased (trial run on
the afternoon of 2026-11-01: "…is located in `stats.py`…" then
"…is defined in `stats.py`…").
"""
from __future__ import annotations

import re

_STRAY_TAGS = re.compile(r"</?tool_call>")

# Below this, two chunks starting the same way may be a coincidence
# ("Okay."), not a rewritten reply.
MIN_REPEAT_CHARS = 30
# Share of a chunk's words found again in a later chunk from which it counts as
# a rephrasing. An announcement ("Reading stats.py.") stays well below.
REPHRASE_OVERLAP = 0.8

_WORD = re.compile(r"\w[\w'-]*")


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}


def _rephrased_later(part: str, later: list[str]) -> bool:
    """True if almost all the words of `part` come back in a later chunk."""
    words = _words(part)
    if len(part) < MIN_REPEAT_CHARS or not words:
        return False
    return any(len(words & _words(p)) / len(words) >= REPHRASE_OVERLAP for p in later)


class AnswerBuilder:
    def __init__(self) -> None:
        self._segments: list[str] = [""]

    def add(self, text: str) -> None:
        """A chunk of text (Token event)."""
        self._segments[-1] += text

    def tool_boundary(self) -> None:
        """A tool call: the text that follows is a new chunk."""
        if self._segments[-1]:
            self._segments.append("")

    def text(self) -> str:
        # An empty <tool_call> tag left by the model does not belong in the reply.
        parts = [p for p in (_STRAY_TAGS.sub("", s).strip() for s in self._segments) if p]
        kept = []
        for i, part in enumerate(parts):
            later = parts[i + 1:]
            repeated = ((len(part) >= MIN_REPEAT_CHARS and any(p.startswith(part) for p in later))
                        or _rephrased_later(part, later))
            if not repeated and part not in kept:
                kept.append(part)
        return "\n\n".join(kept)
