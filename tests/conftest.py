"""Settings shared by the whole test suite.

A terminal that exports FORCE_COLOR (some terminals, CI) makes `rich` write
color codes even when output is captured: the text the tests look for
("prompts: system v3") ended up split by those codes. The `sensai.ui` console
is created at import time, so the variable is removed here, before the tests
import the module.
"""
import os

os.environ.pop("FORCE_COLOR", None)
# The suite exercises team_task from the CLI, whose project is this repo: without this,
# the team pipeline would run pytest on this repo, which would rerun team_task... (ADR-0056).
os.environ["SENSAI_NO_PROJECT_TESTS"] = "1"

import pytest


@pytest.fixture(autouse=True)
def _neutral_generation_parameters():
    """The CLI sets generation parameters for the whole process (ADR-0057):
    without a reset, a test that runs the CLI would leak them into later tests."""
    from sensai.core.ollama_client import set_generation_options, set_request_timeout

    set_generation_options(None)
    set_request_timeout(None)
    yield
    set_generation_options(None)
    set_request_timeout(None)
