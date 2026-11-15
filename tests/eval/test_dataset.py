"""Tests loading the JSONL dataset - feature [EV1], ADR-0019."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from sensai.eval.dataset import DatasetError, load_dataset

SAMPLE = Path(__file__).resolve().parents[2] / "datasets" / "eval" / "ev1_sample.jsonl"


def write(tmp_path, *lines):
    path = tmp_path / "d.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def line(**fields):
    return json.dumps({"id": "a", "question": "Q ?", **fields}, ensure_ascii=False)


def test_minimal_load_and_file_digest(tmp_path):
    path = write(tmp_path, line(), "", line(id="b", answer="R", notes="n",
                                            sources=["t", {"source": "f.py", "text": "x"}]))

    dataset = load_dataset(path)

    assert [c.id for c in dataset.cases] == ["a", "b"]
    assert dataset.cases[0].answer is None and dataset.cases[0].sources == []
    assert dataset.cases[1].sources == ["t", {"source": "f.py", "text": "x"}]
    assert dataset.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(("lines", "expected"), [
    (['{"id": "a", "question": "Q"', ], "line 1: invalid JSON"),
    ([line(), "[1]"], "line 2: each line must be a JSON object"),
    ([line(), "", json.dumps({"question": "Q"})], 'line 3: "id" is required'),
    ([json.dumps({"id": "a"})], 'line 1: "question" is required'),
    ([json.dumps({"id": "a", "question": "  "})], 'line 1: "question" must not be empty'),
    ([line(), line()], 'line 2: id "a" already used on line 1'),
    ([line(anwser="typo")], "line 1: unknown key anwser"),
    ([line(answer=3)], 'line 1: "answer" must be a string'),
    ([line(sources="text")], 'line 1: "sources" must be a list'),
    ([line(sources=[3])], "line 1: sources[1] must be"),
    ([line(sources=[{"source": "f.py"}])], "line 1: sources[1] must be"),
])
def test_errors_name_the_line(tmp_path, lines, expected):
    with pytest.raises(DatasetError, match=re.escape(expected)):
        load_dataset(write(tmp_path, *lines))


def test_missing_or_empty_file(tmp_path):
    with pytest.raises(DatasetError, match="unreadable"):
        load_dataset(tmp_path / "absent.jsonl")
    with pytest.raises(DatasetError, match="empty"):
        load_dataset(write(tmp_path, "", ""))


def test_the_sample_dataset_loads_and_covers_the_five_situations():
    dataset = load_dataset(SAMPLE)

    assert len(dataset.cases) >= 5
    assert all(c.answer for c in dataset.cases)
    # At least one case without any passage: the judge must then mark everything unverifiable.
    assert any(not c.sources for c in dataset.cases)
    assert {"fidele", "contredit", "inverifiable", "off-topic", "sans-source"} <= {
        c.id for c in dataset.cases
    }
