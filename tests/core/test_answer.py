"""The stored text of an answer.

Real trial run on 2026-11-01: chunks glued together, answer rewritten.
"""
from sensai.core.answer import AnswerBuilder


def build(*parts):
    b = AnswerBuilder()
    for p in parts:
        if p is None:
            b.tool_boundary()
        else:
            b.add(p)
    return b.text()


def test_a_single_chunk_is_kept_as_is():
    assert build("Bon", "jour.") == "Bonjour."


def test_chunks_separated_by_a_tool_become_paragraphs():
    assert build("I am reading the file.", None, "The file contains two lines.") == \
        "I am reading the file.\n\nThe file contains two lines."


def test_an_answer_rewritten_after_a_tool_appears_only_once():
    answer = "The file deploiement.txt states the region eu-west-3."
    assert build(answer, None, answer + " No fact stored.") == \
        answer + " No fact stored."


def test_a_short_identical_opening_is_not_taken_for_a_repeat():
    assert build("Okay.", None, "Okay. Here is the rest.") == \
        "Okay.\n\nOkay. Here is the rest."


def test_only_tools_gives_an_empty_answer():
    assert build(None, None) == ""


def test_an_empty_tool_call_tag_is_removed_from_the_stored_text():
    assert build("The task is scheduled.<tool_call>") == "The task is scheduled."


def test_an_answer_rephrased_after_a_tool_appears_only_once():
    """Real trial run on the afternoon of 2026-11-01: same sentence, one verb changed."""
    first = "The function `moyenne` is located in the file `stats.py`, starting at line 4."
    second = "The function `moyenne` is defined in the file `stats.py`, starting at line 4."
    assert build(first, None, second) == second


def test_an_announcement_before_the_tool_is_not_taken_for_a_rephrasing():
    assert build("I will read the file stats.py to check.", None,
                 "The function moyenne divides the sum of the values by their count.") == \
        "I will read the file stats.py to check.\n\n" \
        "The function moyenne divides the sum of the values by their count."
