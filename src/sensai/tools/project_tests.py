"""
The project's tests as the verdict of the team pipeline (ADR-0056, point 3).

Measured with the real model: a model reviewer approved wrong work 6 times
out of 6 as long as it did not receive the written content (retrospective,
section 9). When the project has tests, they decide: they cannot be talked
into it by the developer's report.

Tests run on the host, in the project directory, not in the sandbox: the
sandbox image has neither the project nor its dependencies. That is why
`team_task` is an "execute" risk action the user approves first
(ToolGateway).
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

TIMEOUT_S = 120
# The tail of the output is enough for the developer: the summary and first failures.
OUTPUT_TAIL = 3000

TestRunner = Callable[[], tuple[bool, str]]

# Set for the pytest launched here: if the project's tests themselves launch a
# CodeSensai team (this repo's suite does), that team does not rerun the tests,
# otherwise each level would launch another, endlessly (seen on 2026-11-02).
NO_PROJECT_TESTS = "SENSAI_NO_PROJECT_TESTS"


def has_tests(project: Path) -> bool:
    """A `tests/` directory or `test_*.py` files at the project root."""
    return (project / "tests").is_dir() or any(project.glob("test_*.py"))


def project_test_runner(project: str | Path, timeout_s: float = TIMEOUT_S) -> TestRunner | None:
    """A function that runs `pytest -q -x` in the project, or None without tests."""
    root = Path(project)
    if os.environ.get(NO_PROJECT_TESTS) or not has_tests(root):
        return None

    def run() -> tuple[bool, str]:
        try:
            done = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
                cwd=root, capture_output=True, text=True, timeout=timeout_s,
                env={**os.environ, NO_PROJECT_TESTS: "1"},
            )
        except subprocess.TimeoutExpired:
            return False, f"tests did not finish within {timeout_s:.0f} s"
        except OSError as e:
            return False, f"could not run the tests: {e}"
        output = (done.stdout + done.stderr).strip()
        return done.returncode == 0, output[-OUTPUT_TAIL:]

    return run
