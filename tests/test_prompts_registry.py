"""
Checks the prompt registry actually shipped in the repository — feature [A4].

This test runs in CI: it fails if someone edits an already stored version,
deletes a version file, or merges two branches that created the same
number (ADR-0010). To fix a prompt, store a new version.
"""
from sensai.config import PROJECT_ROOT
from sensai.knowledge.prompt_versions import PromptStore


def test_repository_registry_is_consistent():
    store = PromptStore(PROJECT_ROOT / "prompts")

    assert store.exists()
    assert store.check() == []


def test_agent_prompts_are_versioned():
    store = PromptStore(PROJECT_ROOT / "prompts")

    assert {"system", "memory"} <= set(store.names())
    assert store.load("system") != ""
    assert store.load("memory") != ""
