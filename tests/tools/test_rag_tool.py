"""
Tests for RagTool: RAG search exposed as a tool for the Workstream A ReAct
loop (ADR-0002, ADR-0009 decision 4).

The Tool contract requires that a tool never raises:
`test_ollama_unavailable_returns_a_clean_error` fails if an EmbeddingError
is let through.
"""
from sensai.core.tools import ToolRegistry
from sensai.execution.gateway import ToolGateway
from sensai.execution.tool_policy import Risk, risk_of
from sensai.knowledge.rag import EmbeddingError, RagIndex
from sensai.tools.rag_tool import RagTool
from tests.knowledge.test_rag import FakeEmbedder


def index_with_auth(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "auth.py").write_text(
        "def verify_token(token):\n"
        '    """Verify the login token."""\n'
        "    return bool(token)\n",
        encoding="utf-8",
    )
    index = RagIndex(tmp_path / "rag.db", project="p", embed=FakeEmbedder())
    index.update(project)
    return index


def test_finds_and_cites(tmp_path):
    tool = RagTool(index_with_auth(tmp_path), min_score=0.0)

    result = tool.run(query="verify the login token")

    assert result.ok
    assert "auth.py:1-3" in result.content
    assert result.data["passages"][0]["source"] == "auth.py"


def test_nothing_found_says_so(tmp_path):
    tool = RagTool(index_with_auth(tmp_path), min_score=0.5)

    result = tool.run(query="broker kafka zookeeper")

    assert result.ok
    assert "no relevant passage" in result.content.lower()
    assert result.data["passages"] == []


def test_without_index():
    assert not RagTool().run(query="token").ok


def test_empty_query_rejected(tmp_path):
    assert not RagTool(index_with_auth(tmp_path)).run(query="  ").ok


class Broken:
    def __call__(self, texts):
        raise EmbeddingError("Ollama unreachable")


def test_ollama_unavailable_returns_a_clean_error(tmp_path):
    index = index_with_auth(tmp_path)
    index.embed = Broken()

    result = RagTool(index).run(query="token")

    assert not result.ok
    assert "Ollama unreachable" in result.content


def test_declares_read_risk():
    """ADR-0013: without a declared risk, the gateway treats it as execution
    and would ask for confirmation on every search."""
    assert risk_of(RagTool()) is Risk.READ


def test_gateway_allows_it_without_confirmation(tmp_path):
    registry = ToolRegistry()
    registry.register(RagTool(index_with_auth(tmp_path), min_score=0.0))
    requests = []
    gateway = ToolGateway(registry, confirm=lambda req: requests.append(req) or False)

    result = gateway.call("search_codebase", query="token")

    assert result.ok
    assert requests == [], "a search must not ask for confirmation"


def test_result_presented_as_a_requested_search(tmp_path):
    """Real trial run of 2026-10-14: the tool returned the instruction meant for
    automatically added passages ("ignore them"), which made the model doubt a
    search it had requested itself."""
    result = RagTool(index_with_auth(tmp_path), min_score=0.0).run(query="token")

    assert "automatically" not in result.content
    assert "ignore" not in result.content
    assert '"token"' in result.content


# --- R2: filters by type and folder (US-R2-2) ---------------------------------


def test_filters_are_offered_to_the_model():
    properties = RagTool.parameters["properties"]
    assert properties["kind"]["enum"] == ["code", "doc"]
    assert "path" in properties


def test_doc_filter_excludes_code(tmp_path):
    tool = RagTool(index_with_auth(tmp_path), min_score=0.0)
    result = tool.run(query="login token", kind="doc")
    assert result.ok and result.data["passages"] == []


def test_unknown_filter_ignored(tmp_path):
    tool = RagTool(index_with_auth(tmp_path), min_score=0.0)
    result = tool.run(query="login token", kind="image")
    assert result.data["passages"][0]["source"] == "auth.py"
