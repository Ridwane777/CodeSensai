"""Tests for the sandbox limits and the structured result."""
import math

import pytest

from sensai.execution.sandbox.config import SandboxConfig
from sensai.execution.sandbox.result import ExecutionResult, extract_traceback, parse_error

TB = (
    "Traceback (most recent call last):\n"
    '  File "<string>", line 1, in <module>\n'
    "NameError: name 'x' is not defined\n"
)


def test_traceback_is_extracted_from_stderr():
    assert extract_traceback("warning\n" + TB).startswith("Traceback")


def test_last_traceback_wins_when_exceptions_are_chained():
    chained = TB + "\nDuring handling of the above exception, another exception occurred:\n\n" + TB
    assert extract_traceback(chained).count("Traceback") == 1


def test_no_traceback_gives_none():
    assert extract_traceback("just a warning") is None


@pytest.mark.parametrize(
    ("traceback", "expected"),
    [
        (TB, ("NameError", "name 'x' is not defined")),
        ("Traceback (most recent call last):\nKeyboardInterrupt", ("KeyboardInterrupt", "")),
        ("Traceback (most recent call last):\npkg.errors.Custom: boom", ("Custom", "boom")),
        ("Traceback (most recent call last):\n  indented line", (None, None)),
        (None, (None, None)),
        ("", (None, None)),
    ],
)
def test_error_is_parsed_from_the_last_line(traceback, expected):
    assert parse_error(traceback) == expected


@pytest.mark.parametrize(
    ("asked", "expected"),
    [(None, 10.0), (5, 5.0), (500, 60.0), (0, 10.0), (-3, 10.0), ("x", 10.0)],
)
def test_timeout_is_clamped(asked, expected):
    assert SandboxConfig().clamp_timeout(asked) == expected


@pytest.mark.parametrize("bad", [math.nan, True])
def test_timeout_rejects_nan_and_booleans(bad):
    assert SandboxConfig().clamp_timeout(bad) == 10.0


def test_failure_result_describes_a_problem_outside_the_program():
    result = ExecutionResult.failure("SandboxError", "Docker is down")
    assert result.ok is False
    assert result.exit_code is None
    assert result.to_dict()["error_type"] == "SandboxError"
