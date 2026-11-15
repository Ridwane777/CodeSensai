"""Tests the judge passage providers - feature [EV1], ADR-0019."""
from sensai.eval.sources import (
    NO_PASSAGES,
    Passage,
    format_passages,
    rag_sources,
    static_sources,
)


def test_static_sources_numbers_passages_and_accepts_two_forms():
    passages = static_sources(["raw text", {"source": "src/a.py", "text": "def f(): ..."}])

    assert [p.id for p in passages] == ["S1", "S2"]
    assert passages[0].source == "dataset" and passages[0].text == "raw text"
    assert passages[1].source == "src/a.py"


def test_format_passages_puts_id_and_position_before_the_text():
    text = format_passages([
        Passage("S1", "src/a.py", "def f(): ...", start=10, end=12),
        Passage("S2", "dataset", "raw text"),
    ])

    assert text == "[S1] src/a.py:10-12\ndef f(): ...\n\n[S2] dataset\nraw text"


def test_format_passages_without_passage_says_so():
    assert format_passages([]) == NO_PASSAGES


class FakeIndex:
    """Any object with `.search(query, top_k, min_score)` works (no need for R1)."""

    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search(self, query, top_k, min_score):
        self.calls.append((query, top_k, min_score))
        return self.hits


def test_rag_sources_forwards_the_question_and_converts_results():
    index = FakeIndex([
        {"source": "src/a.py", "start": 1, "end": 5, "text": "def f(): ...", "score": 0.9},
        {"source": "docs/b.md", "start": 3, "end": 4, "text": "# B", "score": 0.7},
    ])

    passages = rag_sources(index, top_k=3, min_score=0.4)("Where is f?")

    assert index.calls == [("Where is f?", 3, 0.4)]
    assert passages == [
        Passage("S1", "src/a.py", "def f(): ...", 1, 5),
        Passage("S2", "docs/b.md", "# B", 3, 4),
    ]


def test_rag_sources_without_result_gives_an_empty_list():
    assert rag_sources(FakeIndex([]), top_k=5, min_score=0.5)("nothing") == []
