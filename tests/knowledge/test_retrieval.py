"""
Tests for advanced RAG - feature [R2].

Each block maps to a user story in docs/user-stories/R2-advanced-rag.md;
the choices under test come from docs/decisions/0032-hybrid-rag-and-reranking.md.

The tests that matter most:
- `test_an_exact_name_surfaces_thanks_to_bm25`: this is the R1 weakness that
  hybrid search fixes.
- `test_failed_reranking_keeps_the_fusion_order`: a model that answers badly
  must never break search.
- `test_threshold_also_applies_to_bm25_passages`: without it, a common word
  would surface an off-topic passage and the agent would make things up (US-R2-3).
"""
import json

import pytest
import requests

from sensai.knowledge.rag import RagIndex
from sensai.knowledge.retrieval import (
    BM25,
    LlmReranker,
    reciprocal_rank_fusion,
    tokenize,
)
from tests.knowledge.test_rag import FakeEmbedder

# --- Building blocks: words, BM25, fusion -------------------------------------


def test_tokenize_splits_code_names():
    assert tokenize("retention_days") == ["retention_days", "retention", "days"]
    assert "store" in tokenize("FactStore")
    assert "factstore" in tokenize("FactStore")


def test_tokenize_ignores_accents_and_stopwords():
    # French input on purpose: STOPWORDS covers French and accents are stripped.
    assert tokenize("Où sont stockés les faits ?") == ["stockes", "faits"]


def test_bm25_prefers_the_document_with_the_rare_word():
    bm25 = BM25(["the project uses python", "FactStore keeps the facts", "python python"])
    assert bm25.search("FactStore", top_k=3)[0][0] == 1


def test_bm25_ignores_documents_without_a_shared_word():
    assert BM25(["alpha", "beta"]).search("gamma", top_k=5) == []


def test_rrf_favors_agreement_between_both_rankings():
    dense = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    words = [{"id": "d"}, {"id": "b"}, {"id": "e"}]
    fusion = reciprocal_rank_fusion([dense, words], key=lambda h: h["id"])
    assert fusion[0]["id"] == "b"  # 2nd in both beats 1st on one side only
    assert {h["id"] for h in fusion} == {"a", "b", "c", "d", "e"}


# --- US-R2-1: reranking by the model ------------------------------------------


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self.content}}


def passages(n):
    return [{"source": f"f{i}.py", "start": 1, "end": 2, "text": f"text {i}"} for i in range(n)]


def test_the_model_reorders_the_top_ones(monkeypatch):
    sent = {}

    def post(url, json, timeout):
        sent.update(json)
        return FakeResponse('{"ordre": [2, 0]}')

    monkeypatch.setattr(requests, "post", post)
    order = LlmReranker("http://h", "m", depth=3)("question", passages(4))
    assert [p["source"] for p in order] == ["f2.py", "f0.py", "f1.py", "f3.py"]
    assert sent["format"] == "json" and "question" in sent["messages"][0]["content"]


@pytest.mark.parametrize("content", ["not json", '{"ordre": "x"}', '{"other": [1]}'])
def test_failed_reranking_keeps_the_fusion_order(monkeypatch, content):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(content))
    order = LlmReranker("http://h", "m")("q", passages(3))
    assert [p["source"] for p in order] == ["f0.py", "f1.py", "f2.py"]


def test_unreachable_model_keeps_the_order(monkeypatch):
    def outage(*a, **k):
        raise requests.ConnectionError("Ollama down")

    monkeypatch.setattr(requests, "post", outage)
    assert LlmReranker("http://h", "m")("q", passages(2)) == passages(2)


def test_invented_or_duplicate_numbers_ignored(monkeypatch):
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: FakeResponse(json.dumps({"ordre": [1, 1, 9, -1]})))
    order = LlmReranker("http://h", "m")("q", passages(3))
    assert [p["source"] for p in order] == ["f1.py", "f0.py", "f2.py"]


def test_a_single_passage_does_not_call_the_model(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("needless call"))
    assert LlmReranker("http://h", "m")("q", passages(1)) == passages(1)


# --- Hybrid search in the index -----------------------------------------------


@pytest.fixture
def index(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "store.py").write_text(
        "class FactStore:\n    def remember(self, entity, value):\n        return value\n",
        encoding="utf-8")
    (root / "src" / "auth.py").write_text(
        "def verify_token(token):\n    return bool(token)\n", encoding="utf-8")
    (root / "docs" / "facts.md").write_text(
        "# Facts\nThe facts the agent remembered about the project.\n", encoding="utf-8")
    idx = RagIndex(tmp_path / "rag.db", project="p", embed=FakeEmbedder())
    idx.update(root)
    return idx


def test_an_exact_name_surfaces_thanks_to_bm25(index):
    results = index.search("FactStore", min_score=0.0)
    assert results[0]["source"] == "src/store.py"


def test_each_passage_keeps_its_similarity_score(index):
    for hit in index.search("facts remembered", min_score=0.0):
        assert 0.0 <= hit["score"] <= 1.0


def test_threshold_also_applies_to_bm25_passages(index):
    # "token" is an exact word of auth.py, but the whole question is far from it.
    assert index.search("token kafka zookeeper broker partition", min_score=0.6) == []


def test_the_reranker_receives_the_candidates(index):
    seen = []

    def reranker(question, hits):
        seen.append(question)
        return list(reversed(hits))

    index.reranker = reranker
    normal = index.search("project facts", min_score=0.0, rerank=False)
    reranked = index.search("project facts", min_score=0.0)
    assert seen == ["project facts"]
    assert reranked[0] != normal[0] or len(normal) == 1


# --- US-R2-2: filters by type and folder --------------------------------------


def test_code_filter(index):
    assert {h["source"] for h in index.search("facts", min_score=0.0, kind="code")} <= {
        "src/store.py", "src/auth.py"}


def test_doc_filter(index):
    sources = {h["source"] for h in index.search("facts", min_score=0.0, kind="doc")}
    assert sources == {"docs/facts.md"}


def test_folder_filter(index):
    sources = {h["source"] for h in index.search("facts token", min_score=0.0, path="src")}
    assert sources and all(s.startswith("src/") for s in sources)


def test_folder_filter_does_not_confuse_prefixes(index):
    assert index.search("facts", min_score=0.0, path="sr") == []


def test_reranking_sends_num_ctx_when_given(monkeypatch):
    """PR #97 review: the reranking prompt pastes up to `depth` passages;
    without num_ctx, Ollama may silently truncate it."""
    sent = {}

    def post(url, json, timeout):
        sent.update(json)
        return FakeResponse('{"ordre": [0, 1]}')

    monkeypatch.setattr(requests, "post", post)
    LlmReranker("http://h", "m", num_ctx=4096)("question", passages(3))
    # Temperature 0 as well: the ranking must be reproducible (ADR-0057).
    assert sent["options"] == {"temperature": 0, "num_ctx": 4096}

    sent.clear()
    LlmReranker("http://h", "m")("question", passages(3))
    assert sent["options"] == {"temperature": 0}
