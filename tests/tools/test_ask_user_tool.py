"""
The `ask_user` tool (X4, ADR-0046): validation of the form, of the answers, and
the terminal version. The web flow is in tests/web/test_questions.py.
"""
import json

import pytest

from sensai.tools.ask_user_tool import (
    MAX_FIELDS,
    AskUserTool,
    FormError,
    check_answers,
    parse_question,
    terminal_asker,
)

FIELDS = [
    {"id": "name", "kind": "text", "label": "Module name"},
    {"id": "style", "kind": "choice", "label": "Style", "options": ["pytest", "unittest"]},
    {"id": "docs", "kind": "toggle", "label": "Add docs?"},
]


def test_a_valid_form_is_accepted():
    q = parse_question("A few details", FIELDS)
    assert q.title == "A few details"
    assert [f["kind"] for f in q.fields] == ["text", "choice", "toggle"]


def test_default_kind_is_text():
    q = parse_question("?", [{"id": "a", "label": "A"}])
    assert q.fields[0]["kind"] == "text"


@pytest.mark.parametrize("title, fields", [
    ("", FIELDS),
    ("?", []),
    ("?", "not a list"),
    ("?", [{"id": "a", "label": "A"}] * 2),  # duplicate id
    ("?", [{"id": "a", "kind": "date", "label": "A"}]),
    ("?", [{"id": "a", "kind": "choice", "label": "A", "options": ["only"]}]),
    ("?", [{"id": "a", "kind": "choice", "label": "A", "options": ["x", "x"]}]),
    ("?", [{"id": "a", "label": ""}]),
    ("?", [{"id": f"f{i}", "label": "L"} for i in range(MAX_FIELDS + 1)]),
    ("x" * 201, FIELDS),
])
def test_an_invalid_form_is_rejected(title, fields):
    with pytest.raises(FormError):
        parse_question(title, fields)


def test_valid_answers_are_accepted():
    q = parse_question("?", FIELDS)
    values = {"name": " tools ", "style": "pytest", "docs": False}
    assert check_answers(q, values) == {"name": "tools", "style": "pytest", "docs": False}


@pytest.mark.parametrize("values", [
    {"name": "a", "style": "pytest"},                       # missing answer
    {"name": "a", "style": "pytest", "docs": True, "x": 1},  # unknown field
    {"name": "a", "style": "nose", "docs": True},           # choice not offered
    {"name": "a", "style": "pytest", "docs": "yes"},        # not a boolean
    {"name": "  ", "style": "pytest", "docs": True},        # empty text
    {"name": 3, "style": "pytest", "docs": True},           # not a string
    ["not", "an", "object"],
])
def test_invalid_answers_are_rejected(values):
    with pytest.raises(FormError):
        check_answers(parse_question("?", FIELDS), values)


def test_the_tool_returns_the_answers_to_the_model():
    tool = AskUserTool(lambda q: {"name": "tools"})
    result = tool.run(title="?", fields=[{"id": "name", "label": "Name"}])
    assert result.ok
    assert json.loads(result.content.split(": ", 1)[1]) == {"name": "tools"}


def test_without_an_answer_the_tool_fails_and_says_so():
    result = AskUserTool(lambda q: None).run(title="?", fields=[{"id": "a", "label": "A"}])
    assert not result.ok and "did not answer" in result.content


def test_without_an_interface_nobody_can_answer():
    result = AskUserTool(None).run(title="?", fields=[{"id": "a", "label": "A"}])
    assert not result.ok and "Nobody can answer" in result.content


def test_an_invalid_form_asks_nobody():
    asked = []
    result = AskUserTool(asked.append).run(title="?", fields=[])
    assert not result.ok and "Invalid form" in result.content and asked == []


def test_the_terminal_asks_each_question():
    # An empty text then a wrong number: asked again.
    answers = iter(["", "tools", "9", "2", "y"])
    shown = []
    ask = terminal_asker(read=lambda prompt: next(answers), show=shown.append)
    values = ask(parse_question("Details", FIELDS))
    assert values == {"name": "tools", "style": "unittest", "docs": True}
    assert any("Details" in line for line in shown)


def test_ctrl_d_in_the_terminal_means_no_answer():
    def eof(prompt):
        raise EOFError
    assert terminal_asker(read=eof, show=lambda s: None)(parse_question("?", FIELDS)) is None
