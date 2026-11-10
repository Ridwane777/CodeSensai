"""
Replays the [EV4] adversarial corpus (tests/adversarial/corpus.py).

A known gap is an `xfail(strict=True)` that asserts the SAFE behavior: the test
stays "expected to fail" while the hole exists, and breaks (XPASS) the day it
is fixed, so the case gets reclassified instead of forgotten.
"""

import re
from collections import Counter
from pathlib import Path

import pytest

from tests.adversarial.corpus import (
    CASES,
    CATEGORIES,
    ID_FORMAT,
    KNOWN,
    OK,
    ROOT,
    AttackCase,
    CaseSkipped,
    Expected,
    render_markdown,
    run_all,
)

RESULTS_FILE = ROOT / "docs" / "performance" / "data" / "EV4-adversarial-results.md"


def _param(case: AttackCase):
    marks = []
    if case.expected is Expected.KNOWN_GAP:
        marks.append(pytest.mark.xfail(strict=True, reason=case.gap))
    return pytest.param(case, id=case.id, marks=marks)


@pytest.mark.parametrize("case", [_param(c) for c in CASES])
def test_attack(case: AttackCase, tmp_path: Path):
    try:
        observed, detail = case.run(tmp_path / "ws")
    except CaseSkipped as exc:
        pytest.skip(str(exc))
    assert observed == case.wanted, (
        f"{case.id}: expected {case.wanted.value}, observed {observed.value} ({detail})"
    )


# -- the corpus itself --------------------------------------------------------


def test_ids_are_unique_and_well_formed():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
    assert all(ID_FORMAT.match(i) for i in ids)


def test_at_least_thirty_cases_and_four_per_category():
    counts = Counter(c.category for c in CASES)
    assert len(CASES) >= 30
    assert set(counts) == set(CATEGORIES)
    assert all(n >= 4 for n in counts.values()), counts


def test_every_known_gap_names_its_cause_with_file_and_line():
    for case in CASES:
        if case.expected is Expected.KNOWN_GAP:
            assert re.search(r"\w+\.py:\d+", case.gap), f"{case.id}: gap without file:line"


def test_cited_lines_exist():
    """Minimal guardrail against stale citations: the file and line exist."""
    for case in CASES:
        for name, line in re.findall(r"(\w+\.py):(\d+)", case.gap):
            matches = list((ROOT / "src").rglob(name))
            assert matches, f"{case.id} cites {name}, not found in src/"
            assert int(line) <= len(matches[0].read_text(encoding="utf-8").splitlines())


# -- the generated document ----------------------------------------------------


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    return run_all(tmp_path_factory.mktemp("ev4"))


def test_results_are_deterministic(full_run, tmp_path: Path):
    assert render_markdown(full_run) == render_markdown(run_all(tmp_path))


def test_committed_results_file_is_up_to_date(full_run):
    """The committed table must be the one the code produces: otherwise the report lies."""
    if not RESULTS_FILE.exists():
        pytest.skip("results not generated yet (python scripts/adversarial_run.py)")
    assert RESULTS_FILE.read_text(encoding="utf-8") == render_markdown(full_run), (
        "docs/performance/data/EV4-adversarial-results.md is stale: "
        "rerun `python scripts/adversarial_run.py`"
    )


def test_no_regression_in_the_run(full_run):
    verdicts = Counter(r.verdict for r in full_run)
    assert set(verdicts) <= {OK, KNOWN}, verdicts


def test_report_contains_the_generated_table():
    """The written report copies the generated table: it must not drift."""
    report = ROOT / "docs" / "security" / "EV4-adversarial-tests.md"
    if not report.exists():
        pytest.skip("report not written yet")
    text = report.read_text(encoding="utf-8")
    rows = [
        line
        for line in RESULTS_FILE.read_text(encoding="utf-8").splitlines()
        if line.startswith("| ")
    ]
    missing = [row[:30] for row in rows if row not in text]
    assert not missing, f"table rows missing from the report: {missing}"


# -- the JSON form served by the Quality page -----------------------------------


def test_committed_results_parse_back_to_the_same_rows(full_run):
    from sensai.eval.adversarial import committed_results, results_to_json

    live = results_to_json(full_run, "2026-11-01T00:00:00+00:00", "run")
    committed = committed_results(RESULTS_FILE)
    strip = [{k: v for k, v in c.items() if k != "detail"} for c in live["cases"]]
    assert [{k: v for k, v in c.items() if k != "detail"} for c in committed["cases"]] == strip
    assert committed["summary"] == live["summary"]
    assert live["summary"] == {
        "total": 85, "ok": 66, "known_gaps": 19, "regressions": 0, "fixed": 0, "skipped": 0,
    }
