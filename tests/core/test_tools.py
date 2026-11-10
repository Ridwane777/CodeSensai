"""
Tests the Tool contract + the ToolRegistry — independently of the agent, the
sandbox or the RAG. Serves as a template for the tests teammates write for
their own tools.
"""
from sensai.core.tools import ToolRegistry
from sensai.tools.echo_tool import EchoTool


def test_register_and_call():
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = registry.call("echo", text="hello")

    assert result.ok is True
    assert result.content == "hello"


def test_unknown_tool_does_not_crash():
    registry = ToolRegistry()

    result = registry.call("tool_that_does_not_exist", text="whatever")

    assert result.ok is False
    assert "unknown" in result.content.lower()


def test_describe_all_lists_registered_tools():
    registry = ToolRegistry()
    registry.register(EchoTool())

    descriptions = registry.describe_all()

    assert len(descriptions) == 1
    assert descriptions[0]["name"] == "echo"


def test_a_parameter_named_name_does_not_break_the_call():
    """The registry already takes a `name` argument (the tool name): it must
    not clash with a tool parameter of the same name."""
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = registry.call("echo", text="x", name="clash")

    assert result.ok is True
