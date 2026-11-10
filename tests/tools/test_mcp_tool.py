"""Tests the MCP client (T1, ADR-0041) against a fake stdio server, without network."""
import sys
from pathlib import Path

import pytest

from sensai.core.tools import ToolRegistry
from sensai.execution.gateway import ToolGateway
from sensai.execution.guardrails import filter_output
from sensai.execution.tool_policy import Risk, risk_of
from sensai.tools.mcp_tool import load_mcp_tools, parse_mcp_config

SERVER = str(Path(__file__).with_name("fake_mcp_server.py"))


def servers(mode="normal", **extra):
    return {"fake": {"command": sys.executable, "args": [SERVER, mode], **extra}}


@pytest.fixture
def loaded():
    tools, warnings, close = load_mcp_tools(parse_mcp_config(servers()))
    yield {t.name: t for t in tools}, warnings
    close()


def test_server_tools_become_agent_tools(loaded):
    tools, warnings = loaded
    assert warnings == []
    assert set(tools) == {"mcp_fake_add", "mcp_fake_leak", "mcp_fake_fail", "mcp_fake_bad_name_"}
    add = tools["mcp_fake_add"]
    assert add.description.startswith("[MCP fake]") and "Adds two" in add.description
    assert add.parameters["required"] == ["a", "b"]
    assert tools["mcp_fake_bad_name_"].parameters == {"type": "object", "properties": {}}


def test_calling_an_mcp_tool(loaded):
    result = loaded[0]["mcp_fake_add"].run(a=2, b=3)
    assert result.ok and result.content == "5"


def test_error_reported_by_the_server(loaded):
    result = loaded[0]["mcp_fake_fail"].run()
    assert not result.ok and "server-side failure" in result.content


def test_risk_is_execute_by_default_and_configurable():
    tools, _, close = load_mcp_tools(parse_mcp_config(servers()))
    assert all(risk_of(t) is Risk.EXECUTE for t in tools)
    close()
    tools, _, close = load_mcp_tools(parse_mcp_config(servers(risk="read")))
    assert all(risk_of(t) is Risk.READ for t in tools)
    close()


def test_gateway_masks_secrets_returned_by_the_server(loaded):
    registry = ToolRegistry()
    for tool in loaded[0].values():
        registry.register(tool)
    gateway = ToolGateway(registry, None, confirm=lambda request: True,
                          output_filters=[filter_output])
    result = gateway.call("mcp_fake_leak")
    assert "sk-abcdef1234567890abcdef" not in result.content


def test_missing_server_does_not_prevent_startup():
    config = {"absent": {"command": "command-that-does-not-exist-xyz"}, **servers()}
    tools, warnings, close = load_mcp_tools(parse_mcp_config(config))
    assert {t.name for t in tools} >= {"mcp_fake_add"}
    assert len(warnings) == 1 and "absent" in warnings[0]
    close()


@pytest.mark.parametrize("mode", ["silent", "garbage"])
def test_silent_or_unreadable_server_is_reported(mode):
    tools, warnings, close = load_mcp_tools(parse_mcp_config(servers(mode, timeout_s=2)))
    assert tools == [] and len(warnings) == 1 and "fake" in warnings[0]
    close()


def test_server_crashing_during_a_call_returns_an_error_without_raising():
    tools, _, close = load_mcp_tools(parse_mcp_config(servers("crash", timeout_s=3)))
    add = next(t for t in tools if t.name == "mcp_fake_add")
    result = add.run(a=1, b=2)
    assert not result.ok and "fake" in result.content
    assert not add.run(a=1, b=2).ok, "the next call fails cleanly too"
    close()


@pytest.mark.parametrize("bad, message", [
    ({"x": {"args": []}}, "command"),
    ({"x": {"command": "a", "risk": "dangerous"}}, "risk"),
    ({"x": {"command": "a", "unknown_key": 1}}, "unknown_key"),
    ({"x y": {"command": "a"}}, "name"),
    ([], "object"),
])
def test_invalid_configuration_is_rejected(bad, message):
    with pytest.raises(ValueError, match=message):
        parse_mcp_config(bad)


def test_no_configuration_means_no_server():
    assert parse_mcp_config(None) == {}
    tools, warnings, close = load_mcp_tools({})
    assert tools == [] and warnings == []
    close()


def test_confirmation_says_which_server_and_which_arguments(loaded):
    text = loaded[0]["mcp_fake_add"].describe_call(a=2, b=3)
    assert "add" in text and "fake" in text and '"a": 2' in text
