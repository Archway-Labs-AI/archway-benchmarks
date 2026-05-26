"""Functor integration seam: real adapter → scorer → store, no GT shortcut.

This test is the single highest-leverage validation in the harness. The
noise stub generates predictions from GT and therefore does NOT exercise
the coordinate-mapping that breaks first when a real engine is wired in.

Here we use a hand-authored `ArchwayAnalysisResult` (the agreed engine
contract — see `tests/fixtures/archway_fixture.py`) with **deliberate
defects** planted across all three TypeEvalPy kinds:

  - `col_offset` off-by-one on a return       -> LOCATION_MISS
  - `line_number` off-by-one on a return      -> LOCATION_MISS
  - function parameter renamed                -> LOCATION_MISS
  - right location, wrong type on a parameter -> TYPE_MISS
  - all other annotations correct             -> EXACT

After the seam runs, the inspector (driven off the store) must classify
each annotation into exactly the right bucket. If a planted plumbing
defect surfaces as TYPE_MISS, the seam test fails — the inspector would
be telling Ben the wrong story about his first real plug-in.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from archway_benchmarks.benchmarks import TypeEvalPyBenchmark
from archway_benchmarks.coverage import CoverageStatus
from archway_benchmarks.outcome import Outcome
from archway_benchmarks.runner import run
from archway_benchmarks.store import connect, list_annotations
from tests.fixtures.archway_fixture import (
    ArchwayAnalysisResult,
    ArchwayAnalysisResultAdapter,
    FixtureAnalysisEngine,
    FixtureTranslationEngine,
    build_args_multiple_fixture,
)

SUITE_PATH = "args/multiple"


@pytest.fixture
def seam_run(tmp_path):
    """Build the fixture, drive it through the real harness Runner, and
    return (run_id, db_path) for downstream assertions."""
    db = tmp_path / "seam.db"
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()
    target = next(s for s in snippets if s.suite_path == SUITE_PATH)
    fixture = build_args_multiple_fixture(target)

    # Mark every other snippet as UNSUPPORTED so the dashboard's covered-
    # subset metric remains meaningful (covered = just our one snippet).
    fixtures_by_path: dict[str, ArchwayAnalysisResult] = {target.file_path: fixture}

    def probe(snip):
        return (
            CoverageStatus.COVERED if snip.suite_path == SUITE_PATH else CoverageStatus.UNSUPPORTED
        )

    translator = FixtureTranslationEngine()
    analyzer = FixtureAnalysisEngine(fixtures_by_path)
    adapter = ArchwayAnalysisResultAdapter()

    result = run(
        benchmark=bench,
        translator=translator,
        analyzer=analyzer,
        adapter=adapter,
        coverage_probe=probe,
        stub_accuracy=None,
        seed=None,
        notes="functor integration seam",
        db_path=db,
    )
    return result.run_id, db


def _by_signature(rows, line, col, kind, name):
    matches = [
        r for r in rows
        if r["line"] == line and r["col"] == col and r["kind"] == kind and r["name"] == name
    ]
    assert matches, f"no annotation for line={line} col={col} kind={kind} name={name}"
    return matches[0]


def test_planted_col_offset_defect_surfaces_as_location_miss(seam_run):
    run_id, db = seam_run
    with connect(db) as conn:
        anns = list_annotations(conn, run_id)
    # GT for my_sum return is at line 4 col 5 (kind=return, name=my_sum).
    row = _by_signature(anns, line=4, col=5, kind="return", name="my_sum")
    assert row["outcome"] == Outcome.LOCATION_MISS.value, (
        "Col-offset off-by-one is a plumbing bug — must NOT surface as TYPE_MISS. "
        f"Got: {row['outcome']}, predicted_types={row['predicted_types']!r}"
    )


def test_planted_line_number_defect_surfaces_as_location_miss(seam_run):
    run_id, db = seam_run
    with connect(db) as conn:
        anns = list_annotations(conn, run_id)
    # GT for func return is at line 11 col 5.
    row = _by_signature(anns, line=11, col=5, kind="return", name="func")
    assert row["outcome"] == Outcome.LOCATION_MISS.value, (
        f"Wrong line number is a plumbing bug; got {row['outcome']}"
    )


def test_planted_parameter_rename_surfaces_as_location_miss(seam_run):
    run_id, db = seam_run
    with connect(db) as conn:
        anns = list_annotations(conn, run_id)
    # GT param `a` of func at line 11 col 10.
    row = _by_signature(anns, line=11, col=10, kind="parameter", name="a")
    assert row["outcome"] == Outcome.LOCATION_MISS.value, (
        "Renaming a parameter is a plumbing bug, not a wrong-type bug. "
        f"Got: {row['outcome']}"
    )


def test_wrong_type_at_correct_location_surfaces_as_type_miss(seam_run):
    run_id, db = seam_run
    with connect(db) as conn:
        anns = list_annotations(conn, run_id)
    # GT param `a` of my_sum at line 4 col 12 (int); fixture predicts str.
    row = _by_signature(anns, line=4, col=12, kind="parameter", name="a")
    assert row["outcome"] == Outcome.TYPE_MISS.value, (
        "Right location, wrong type is a functor bug — must surface as TYPE_MISS. "
        f"Got: {row['outcome']}, expected={row['expected_types']!r} predicted={row['predicted_types']!r}"
    )


def test_clean_annotations_surface_as_exact(seam_run):
    run_id, db = seam_run
    with connect(db) as conn:
        anns = list_annotations(conn, run_id, outcome=Outcome.EXACT)
    suite_anns = [a for a in anns if a["suite_path"] == SUITE_PATH]
    # 5 of the 10 fixture entries are clean; another (my_sum return) misses
    # on col offset; another (func return) misses on line; another (func.a)
    # misses on name; one (my_sum.a) is TYPE_MISS. That leaves 6 EXACT.
    assert len(suite_anns) == 6, (
        f"expected 6 EXACT annotations, got {len(suite_anns)}: "
        f"{[(a['line'], a['col'], a['kind'], a['name']) for a in suite_anns]}"
    )


def test_inspector_filter_separates_plumbing_from_functor_bugs(seam_run):
    """The whole point of the inspector is `outcome=LOCATION_MISS` →
    "plumbing/coordinate bug" and `outcome=TYPE_MISS` → "wrong type / functor".
    Verify both filters return the expected planted defects."""
    run_id, db = seam_run
    with connect(db) as conn:
        plumbing = list_annotations(conn, run_id, outcome=Outcome.LOCATION_MISS)
        functor = list_annotations(conn, run_id, outcome=Outcome.TYPE_MISS)

    plumbing_for_suite = [r for r in plumbing if r["suite_path"] == SUITE_PATH]
    functor_for_suite = [r for r in functor if r["suite_path"] == SUITE_PATH]

    # Three planted plumbing defects in this snippet (col, line, name renames).
    plumbing_keys = {(r["line"], r["col"], r["kind"], r["name"]) for r in plumbing_for_suite}
    assert plumbing_keys == {
        (4, 5, "return", "my_sum"),
        (11, 5, "return", "func"),
        (11, 10, "parameter", "a"),
    }, plumbing_keys

    # Exactly one functor defect.
    functor_keys = {(r["line"], r["col"], r["kind"], r["name"]) for r in functor_for_suite}
    assert functor_keys == {(4, 12, "parameter", "a")}, functor_keys
