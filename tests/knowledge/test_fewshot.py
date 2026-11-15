"""
Tests few-shot example selection - feature [A7], ADR-0044.

Same `FakeEmbedder` (hashed bag of words) as `test_rag.py`: two questions
sharing words have close vectors, which is enough to test the search
without Ollama.
"""
import pytest

from sensai.eval.dataset import DatasetError
from sensai.knowledge.fewshot import Example, FewShotError, FewShotIndex, format_example
from tests.knowledge.test_rag import FakeEmbedder


@pytest.fixture
def exemples(tmp_path):
    path = tmp_path / "exemples.jsonl"
    path.write_text(
        '{"id": "1", "question": "Explain the verifier_token function",'
        ' "answer": "It compares the received token with the expected secret."}\n'
        '{"id": "2", "question": "How does the answer cache work?",'
        ' "answer": "It serves the already computed answer for a close question."}\n'
        '{"id": "3", "question": "Case without an answer",'
        ' "notes": "ignored: no answer"}\n',
        encoding="utf-8",
    )
    return path


def test_loads_only_cases_with_an_answer(exemples):
    index = FewShotIndex(FakeEmbedder())
    assert index.load(str(exemples)) == 2


def test_file_without_usable_case_is_refused(tmp_path):
    path = tmp_path / "vide.jsonl"
    path.write_text('{"id": "1", "question": "No answer"}\n', encoding="utf-8")
    index = FewShotIndex(FakeEmbedder())
    with pytest.raises(FewShotError, match="answer"):
        index.load(str(path))


def test_unreadable_file_raises_fewshoterror(tmp_path):
    index = FewShotIndex(FakeEmbedder())
    with pytest.raises(FewShotError):
        index.load(str(tmp_path / "absent.jsonl"))


def test_malformed_file_raises_fewshoterror(tmp_path):
    path = tmp_path / "mauvais.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    index = FewShotIndex(FakeEmbedder())
    with pytest.raises(FewShotError):
        index.load(str(path))


def test_load_error_keeps_the_dataset_error_message(exemples, monkeypatch):
    """FewShotError wraps DatasetError, it does not silently replace it."""
    import sensai.knowledge.fewshot as fewshot_module

    def _echoue(path):
        raise DatasetError("line 1: broken")

    monkeypatch.setattr(fewshot_module, "load_dataset", _echoue)
    index = FewShotIndex(FakeEmbedder())
    with pytest.raises(FewShotError, match="broken"):
        index.load(str(exemples))


def test_best_match_finds_the_closest_example(exemples):
    index = FewShotIndex(FakeEmbedder(), min_score=0.1)
    index.load(str(exemples))

    best = index.best_match("Explain what the verifier_token function checks")
    assert best is not None
    assert best.question == "Explain the verifier_token function"


def test_best_match_below_threshold_returns_none(exemples):
    index = FewShotIndex(FakeEmbedder(), min_score=0.99)
    index.load(str(exemples))

    assert index.best_match("A completely unrelated question") is None


def test_best_match_without_loaded_index_returns_none():
    index = FewShotIndex(FakeEmbedder())
    assert index.best_match("whatever") is None


def test_format_example_has_question_and_answer_without_answering_for_it():
    texte = format_example(Example(question="Q ?", answer="R."))
    assert "Q ?" in texte
    assert "R." in texte
    assert "do not answer this example" in texte


def test_example_yields_to_user_preferences():
    """Real trial run on 2026-11-01: a French-language example won over "answer in English"."""
    from sensai.knowledge.fewshot import Example, format_example

    text = format_example(Example(question="How do I run the tests?", answer="pytest -q"))
    assert "user preferences" in text and "take precedence" in text


def test_preferences_are_repeated_next_to_the_example():
    """Real trial run on 2026-11-01: in the system prompt only, "answer in
    English" lost to a French-language example, three times out of three."""
    text = format_example(Example(question="Q ?", answer="R."), ["Always answer in English."])
    assert text.rstrip().endswith("Always answer in English.]")
    sans = format_example(Example(question="Q ?", answer="R."))
    assert "User preferences" not in sans.split("]\n", 1)[1]


def test_identical_example_not_attached_when_preferences_exist():
    """Real trial run on 2026-11-01 afternoon: the example question, word for
    word, got its answer in French despite "answer in English"."""
    from sensai.knowledge.fewshot import worth_attaching

    ex = Example(question="How do I run the project tests?", answer="pytest -q")
    prefs = ["Always answer in English."]
    assert not worth_attaching(ex, "how do i run the project tests", prefs)
    assert worth_attaching(ex, "How do I run the project tests?")
    assert worth_attaching(ex, "Which command runs the tests?", prefs)
