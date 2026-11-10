"""
Tests the registry shared by the CLI and the scheduler (X5).

`test_workstream_b_tools_are_offered` fails if a shipped tool is no longer
registered: that is what left the agent without `run_code` or `read_file` in
conversation (real trial run on 2026-10-14).
"""
from sensai.execution.tool_policy import Risk, risk_of
from sensai.registry import build_registry


def test_workstream_b_tools_are_offered():
    names = {d["name"] for d in build_registry().describe_all()}

    assert {"run_code", "read_file", "write_file", "web_search"} <= names


def test_each_tool_declares_its_risk():
    """A missing risk is treated as execution: we want the real level."""
    registry = build_registry()
    risks = {d["name"]: risk_of(registry.get(d["name"])) for d in registry.describe_all()}

    assert risks["read_file"] is Risk.READ
    assert risks["write_file"] is Risk.WRITE
    assert risks["run_code"] is Risk.EXECUTE
    assert risks["web_search"] is Risk.NETWORK


def test_building_the_registry_starts_no_container(monkeypatch):
    """The CLI builds the registry at startup: Docker must only be contacted
    on the first tool call, not before (CLI usable without Docker)."""
    import sensai.execution.sandbox.docker_utils as docker_utils

    def forbidden():
        raise AssertionError("Docker contacted while building the registry")

    monkeypatch.setattr(docker_utils, "connect", forbidden)

    build_registry()
