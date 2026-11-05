"""Teste la validation des arguments et des résultats d'outils."""
import pytest

from sensai.core.tools import ToolResult
from sensai.execution.tool_validation import check_arguments, check_result

SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "timeout": {"type": "integer"},
        "mode": {"type": "string", "enum": ["fast", "safe"]},
    },
    "required": ["code"],
}


def test_valid_arguments_pass():
    assert check_arguments(SCHEMA, {"code": "print(1)", "timeout": 5}) is None


def test_missing_required_field():
    assert "code" in check_arguments(SCHEMA, {})


def test_wrong_type():
    assert "string" in check_arguments(SCHEMA, {"code": 42})


def test_bool_is_not_an_integer():
    assert check_arguments(SCHEMA, {"code": "x", "timeout": True}) is not None


def test_enum_is_enforced():
    assert check_arguments(SCHEMA, {"code": "x", "mode": "yolo"}) is not None


def test_extra_fields_allowed_by_default():
    # Les petits modèles ajoutent souvent un champ en trop : on le tolère,
    # sauf si l'outil demande additionalProperties: false.
    assert check_arguments(SCHEMA, {"code": "x", "bonus": 1}) is None
    strict = {**SCHEMA, "additionalProperties": False}
    assert "bonus" in check_arguments(strict, {"code": "x", "bonus": 1})


def test_arguments_must_be_an_object():
    assert check_arguments(SCHEMA, ["code"]) is not None


def test_valid_result_passes():
    assert check_result(ToolResult(ok=True, content="ok", data={"a": 1})) is None


@pytest.mark.parametrize(
    "bad",
    [
        "pas un ToolResult",
        None,
        ToolResult(ok=True, content=123),  # type: ignore[arg-type]
        ToolResult(ok=True, content="x", data=["pas", "un", "dict"]),  # type: ignore[arg-type]
        ToolResult(ok=True, content="x", data={"f": object()}),
        ToolResult(ok="oui", content="x"),  # type: ignore[arg-type]
    ],
)
def test_invalid_results_are_rejected(bad):
    assert check_result(bad) is not None


def test_output_schema_checked_on_success_only():
    out = {"type": "object", "required": ["rows"], "properties": {"rows": {"type": "integer"}}}
    assert check_result(ToolResult(ok=True, content="x", data={}), out) is not None
    assert check_result(ToolResult(ok=True, content="x", data={"rows": 3}), out) is None
    # Un échec n'a pas à respecter le schéma de succès.
    assert check_result(ToolResult(ok=False, content="échec"), out) is None
