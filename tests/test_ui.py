"""
Tests the CLI display (src/sensai/ui.py) without a terminal: tool summaries,
labels, the numbered diff and the instruction given after a refusal.
Interactive rendering (colors, spinner, menu) is checked by hand.
"""
from rich.console import Console

from sensai import ui
from sensai.core.events import ToolCall


def render(renderable) -> str:
    console = Console(record=True, width=100, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_useful_summaries_rather_than_first_line():
    assert ui.tool_summary("read_file", True, "a\nb\nc\nd") == "4 lines read"
    assert ui.tool_summary("write_file", True, "Created x.py (8 bytes).") == "File created"
    assert ui.tool_summary("write_file", True, "Replaced x.py (8 bytes).") == "File modified"
    results = "Results for: q\n1. A\n   u\n2. B"
    assert ui.tool_summary("web_search", True, results) == "2 result(s)"
    assert ui.tool_summary(
        "search_codebase", True, '[Search "q": 5 passage(s) from the project.]') == \
        "5 passage(s) found"
    assert ui.tool_summary("recall_facts", True, "Facts found:\n- a\n- b") == \
        "2 fact(s) found"


def test_failure_shows_the_message():
    assert ui.tool_summary("run_code", False, "Execution failed: NameError\nTrace") == \
        "Execution failed: NameError"


def test_readable_labels():
    assert str(ui.tool_label(ToolCall(id="1", name="read_file",
                                      arguments={"path": "calc.py"}))) == "Read(calc.py)"
    assert str(ui.tool_label(ToolCall(id="2", name="run_code",
                                      arguments={"code": "print(1)\nprint(2)"}))) == \
        "Run(print(1))"
    assert str(ui.tool_label(ToolCall(id="3", name="unknown_tool"))) == "unknown_tool"


def test_numbered_diff_without_headers():
    diff = ("REPLACE calc.py\n--- before\n+++ after\n@@ -1,2 +1,2 @@\n"
            " def mean(values):\n-    return len(value)\n+    return len(values)")

    text = render(ui.diff_view(diff))

    assert "--- before" not in text and "+++ after" not in text
    assert "2 -    return len(value)" in text
    assert "2 +    return len(values)" in text
    assert "1  def mean(values):" in text


def test_text_without_diff_shown_as_is():
    assert "Remember: auth" in render(ui.diff_view("Remember: auth — port: 8080"))


def test_instruction_is_given_only_once(monkeypatch):
    monkeypatch.setattr(ui, "_pending_instruction", "use pytest instead")

    assert ui.take_instruction() == "use pytest instead"
    assert ui.take_instruction() is None


def test_call_written_as_text_is_not_shown():
    answer = "Reading the file.\n<function=read_file>\n<parameter=path>\nx\n</parameter>"

    assert ui.visible_answer(answer) == "Reading the file."
    assert ui.visible_answer("<tool_call>\n<function=x>") == ""
    assert ui.visible_answer("Normal answer.") == "Normal answer."
