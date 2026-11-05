"""Teste les modes de permission et les préférences d'outils."""
import json

import pytest

from sensai.execution.tool_policy import (
    Mode,
    Risk,
    ToolPreferences,
    effective_mode,
    risk_of,
)


class _Declared:
    risk = "write"


class _Undeclared:
    pass


class _Garbage:
    risk = "inoffensif"


def test_risk_is_read_from_the_tool():
    assert risk_of(_Declared()) is Risk.WRITE


@pytest.mark.parametrize("tool", [_Undeclared(), _Garbage()])
def test_missing_or_invalid_risk_is_treated_as_execute(tool):
    # Échec fermé : un outil sans risque déclaré ne doit pas passer pour sûr.
    assert risk_of(tool) is Risk.EXECUTE


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        (Risk.READ, Mode.ALLOW),
        (Risk.NETWORK, Mode.ALLOW),
        (Risk.WRITE, Mode.ASK),
        (Risk.EXECUTE, Mode.ASK),
    ],
)
def test_default_modes(risk, expected):
    assert effective_mode("t", risk, ToolPreferences()) is expected


def test_preferences_can_tighten_any_risk():
    prefs = ToolPreferences(modes={"t": Mode.DENY})
    assert effective_mode("t", Risk.READ, prefs) is Mode.DENY
    assert effective_mode("t", Risk.EXECUTE, prefs) is Mode.DENY


def test_preferences_can_loosen_read_and_network():
    prefs = ToolPreferences(modes={"t": Mode.ASK})
    assert effective_mode("t", Risk.READ, prefs) is Mode.ASK
    prefs = ToolPreferences(modes={"t": Mode.ALLOW})
    assert effective_mode("t", Risk.NETWORK, prefs) is Mode.ALLOW


@pytest.mark.parametrize("risk", [Risk.WRITE, Risk.EXECUTE])
def test_preferences_cannot_loosen_write_or_execute(risk):
    # Ce test échoue si on retire le plancher : "allow" désactiverait A3.
    prefs = ToolPreferences(modes={"t": Mode.ALLOW})
    assert effective_mode("t", risk, prefs) is Mode.ASK


def test_from_dict_parses_all_fields():
    prefs = ToolPreferences.from_dict(
        {
            "disabled": ["web_search"],
            "modes": {"run_code": "deny"},
            "max_output_chars": 500,
            "confirm_timeout_s": 30,
            "tool_timeout_s": 5,
            "confirm_after_untrusted": True,
        }
    )
    assert prefs.disabled == frozenset({"web_search"})
    assert prefs.modes == {"run_code": Mode.DENY}
    assert prefs.max_output_chars == 500
    assert prefs.confirm_timeout_s == 30.0
    assert prefs.tool_timeout_s == 5.0
    assert prefs.confirm_after_untrusted is True


def test_from_dict_empty_gives_defaults():
    assert ToolPreferences.from_dict({}) == ToolPreferences()


@pytest.mark.parametrize(
    "bad",
    [
        {"disable": ["x"]},  # faute de frappe sur la clé
        {"modes": {"x": "autoriser"}},
        {"modes": ["x"]},
        {"disabled": "x"},
        {"max_output_chars": 0},
        {"max_output_chars": True},
        {"confirm_timeout_s": -1},
        {"tool_timeout_s": 0},
        {"tool_timeout_s": "vite"},
        {"confirm_after_untrusted": "yes"},
    ],
)
def test_from_dict_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        ToolPreferences.from_dict(bad)


def test_load_reads_json_file(tmp_path):
    path = tmp_path / "tools.json"
    path.write_text(json.dumps({"disabled": ["a"]}), encoding="utf-8")
    assert ToolPreferences.load(path).disabled == frozenset({"a"})


def test_confirm_after_untrusted_is_off_by_default():
    assert ToolPreferences().confirm_after_untrusted is False
