"""
[Workstream D] Asking the user a question — feature [X4] Questions & Forms (ADR-0046).

The agent calls `ask_user` when it lacks information it cannot find on its
own (a choice, a name, a preference). The tool does not know how answers are
given: it receives an `Asker`, provided by the interface.

- CLI: `terminal_asker` asks the questions one by one in the terminal.
- Web: `sensai.web.questions.WebQuestionBroker` sends a form to the browser
  and waits for the answer (same mechanism as confirmation, ADR-0015).

Rules:
- The fields come from the model: they are validated here (types, count,
  sizes) before being shown. An invalid form is a tool failure the model can fix.
- No answer (timeout, tab closed, interruption): the tool fails and says so;
  the agent must not make up the answer.
- The answers go back to the model as a tool result: the gateway applies the
  same filters as to any output (EV2), so a secret typed by mistake is masked.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from sensai.core.tools import ToolResult

MAX_FIELDS = 8
MAX_OPTIONS = 12
MAX_LABEL_CHARS = 200
MAX_ANSWER_CHARS = 2000
# The time left to the user to answer. Below the tool timeout (`timeout_s`),
# itself below `tool_timeout_s` (120 s by default): otherwise the gateway would
# cut the tool off before it could say "no answer".
ANSWER_TIMEOUT_S = 100.0
KINDS = ("text", "choice", "toggle")


@dataclass(frozen=True)
class Question:
    """A validated form, ready to be shown."""

    title: str
    fields: tuple[dict[str, Any], ...]


# Returns the entered values (field id -> value), or None if the user did
# not answer.
Asker = Callable[[Question], "dict[str, Any] | None"]


class FormError(ValueError):
    """Invalid form or answer; the message is meant for the model or the client."""


def _text(value: Any, what: str, limit: int = MAX_LABEL_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormError(f"{what} must be a non-empty string")
    if len(value) > limit:
        raise FormError(f"{what} exceeds {limit} characters")
    return value.strip()


def parse_question(title: Any, fields: Any) -> Question:
    """Validates the form proposed by the model. Raises FormError."""
    clean_title = _text(title, "title")
    if not isinstance(fields, list) or not fields:
        raise FormError("fields must be a non-empty list")
    if len(fields) > MAX_FIELDS:
        raise FormError(f"at most {MAX_FIELDS} fields")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(fields):
        if not isinstance(raw, dict):
            raise FormError(f"fields[{i}] must be an object")
        field_id = _text(raw.get("id"), f"fields[{i}].id", 64)
        if field_id in seen:
            raise FormError(f"duplicate field id: {field_id}")
        seen.add(field_id)
        kind = raw.get("kind", "text")
        if kind not in KINDS:
            raise FormError(f"fields[{i}].kind must be one of {', '.join(KINDS)}")
        field: dict[str, Any] = {"id": field_id, "kind": kind,
                                 "label": _text(raw.get("label"), f"fields[{i}].label")}
        if kind == "choice":
            options = raw.get("options")
            if not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS:
                raise FormError(f"fields[{i}].options: between 2 and {MAX_OPTIONS} choices")
            field["options"] = [_text(o, f"fields[{i}].options") for o in options]
            if len(set(field["options"])) != len(field["options"]):
                raise FormError(f"fields[{i}].options: duplicate choice")
        elif kind == "text" and raw.get("placeholder") is not None:
            field["placeholder"] = _text(raw.get("placeholder"), f"fields[{i}].placeholder")
        out.append(field)
    return Question(clean_title, tuple(out))


def check_answers(question: Question, values: Any) -> dict[str, Any]:
    """Checks the received values against the form. Raises FormError.

    Each field must have a value of the right type: a (non-empty) string, one of
    the offered choices, or a boolean. Nothing else is accepted.
    """
    if not isinstance(values, dict):
        raise FormError("the answers must be an object")
    expected = {f["id"]: f for f in question.fields}
    unknown = set(values) - set(expected)
    if unknown:
        raise FormError(f"unknown field: {sorted(unknown)[0]}")
    clean: dict[str, Any] = {}
    for field_id, field in expected.items():
        if field_id not in values:
            raise FormError(f"missing answer: {field_id}")
        value = values[field_id]
        if field["kind"] == "toggle":
            if not isinstance(value, bool):
                raise FormError(f"{field_id} must be true or false")
        elif field["kind"] == "choice":
            if value not in field["options"]:
                raise FormError(f"{field_id}: unknown choice")
        else:
            value = _text(value, field_id, MAX_ANSWER_CHARS)
        clean[field_id] = value
    return clean


class AskUserTool:
    name = "ask_user"
    description = (
        "Asks the user a question as a small form and waits for the answer. Use it "
        "only when you lack information you can neither find in the project nor infer "
        "(a choice between several options, a name, a preference). One short question, "
        "a few fields at most. If the tool fails for lack of an answer, do not make up "
        "the answer: say what is missing."
    )
    # Touches nothing: only a person is asked.
    risk = "read"
    timeout_s = ANSWER_TIMEOUT_S + 10.0
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The question, in one sentence."},
            "fields": {
                "type": "array",
                "description": (
                    "The requested information. kind: text (free answer), choice "
                    "(one of options), toggle (yes / no)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "label": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "placeholder": {"type": "string"},
                    },
                    "required": ["id", "label"],
                },
            },
        },
        "required": ["title", "fields"],
        "additionalProperties": False,
    }

    def __init__(self, asker: Asker | None) -> None:
        self.asker = asker

    def describe_call(self, **args: Any) -> str:
        return f"Ask the user: {args.get('title', '')}"

    def run(self, **kwargs: Any) -> ToolResult:
        if self.asker is None:
            return ToolResult(ok=False, content="Nobody can answer here "
                                                "(running without an interface).")
        try:
            question = parse_question(kwargs.get("title"), kwargs.get("fields"))
        except FormError as e:
            return ToolResult(ok=False, content=f"Invalid form: {e}.")
        values = self.asker(question)
        if values is None:
            return ToolResult(ok=False, content="The user did not answer: do not assume "
                                                "the answer, say what you are missing.")
        return ToolResult(ok=True, content="User answers: "
                                           + json.dumps(values, ensure_ascii=False))


def terminal_asker(read: Callable[[str], str] = input,
                   show: Callable[[str], None] = print) -> Asker:
    """The CLI `Asker`: one question per line. Ctrl+D or Ctrl+C: no answer."""

    def ask(question: Question) -> dict[str, Any] | None:
        show(f"\n? {question.title}")
        values: dict[str, Any] = {}
        try:
            for field in question.fields:
                if field["kind"] == "choice":
                    for n, option in enumerate(field["options"], 1):
                        show(f"  {n}. {option}")
                    while True:
                        raw = read(f"  {field['label']} (number): ").strip()
                        if raw.isdigit() and 1 <= int(raw) <= len(field["options"]):
                            values[field["id"]] = field["options"][int(raw) - 1]
                            break
                elif field["kind"] == "toggle":
                    raw = read(f"  {field['label']} (y/n): ").strip().lower()
                    values[field["id"]] = raw in ("y", "yes", "o", "oui")
                else:
                    while not (raw := read(f"  {field['label']}: ").strip()):
                        pass
                    values[field["id"]] = raw[:MAX_ANSWER_CHARS]
        except (EOFError, KeyboardInterrupt):
            return None
        return values

    return ask
