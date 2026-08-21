"""BugsInPy scoring (both modes) + store + report tests, on the fixture corpus."""
from __future__ import annotations

from pathlib import Path

import pytest

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark
from archway_benchmarks.bugsinpy_types import BugLocation
from archway_benchmarks.bugsinpy_protocol import RankedFinding, RankedPredictionBundle

FIXTURE = Path(__file__).parent / "fixtures" / "bugsinpy"


@pytest.fixture
def bench() -> BugsInPyBenchmark:
    return BugsInPyBenchmark(corpus_root=FIXTURE)


# ----- detection mode -----

def test_detection_hit_on_exact_line(bench):
    from archway_benchmarks.scoring.bugsinpy import score_detection

    flagged = {"demoproj:1": [BugLocation(file="demoproj/core.py", start=11, end=11,
                                          lines=frozenset({11}))]}
    scores, outcomes = score_detection(bench, flagged)
    assert scores.total_bugs == 3
    assert scores.detected == 1
    assert scores.bugs_attempted == 1
    hit = next(o for o in outcomes if o.bug_key == "demoproj:1")
    assert hit.kind == "DETECTED"


def test_detection_wrong_file_is_not_a_hit(bench):
    from archway_benchmarks.scoring.bugsinpy import score_detection

    flagged = {"demoproj:1": [BugLocation(file="demoproj/WRONG.py", start=11, end=11,
                                          lines=frozenset({11}))]}
    scores, outcomes = score_detection(bench, flagged)
    assert scores.detected == 0
    assert scores.file_level_detected == 0
    assert next(o for o in outcomes if o.bug_key == "demoproj:1").kind == "MISSED"


def test_detection_right_file_wrong_line(bench):
    from archway_benchmarks.scoring.bugsinpy import score_detection

    flagged = {"demoproj:1": [BugLocation(file="demoproj/core.py", start=999, end=999,
                                          lines=frozenset({999}))]}
    scores, outcomes = score_detection(bench, flagged)
    assert scores.detected == 0
    assert scores.file_level_detected == 1  # right file, wrong line
    assert next(o for o in outcomes if o.bug_key == "demoproj:1").kind == "WRONG_FILE"


def test_detection_line_tolerance(bench):
    from archway_benchmarks.scoring.bugsinpy import score_detection

    flagged = {"demoproj:1": [BugLocation(file="demoproj/core.py", start=13, end=13,
                                          lines=frozenset({13}))]}
    strict, _ = score_detection(bench, flagged, line_tolerance=0)
    loose, _ = score_detection(bench, flagged, line_tolerance=3)
    assert strict.detected == 0
    assert loose.detected == 1  # 13 within ±3 of GT line 11


def test_detection_subset_changes_denominator(bench):
    from archway_benchmarks.scoring.bugsinpy import score_detection

    flagged = {"demoproj:1": [BugLocation(file="demoproj/core.py", start=11, end=11,
                                          lines=frozenset({11}))]}
    scores, _ = score_detection(bench, flagged, subset={"demoproj:1", "demoproj:2"})
    assert scores.total_bugs == 2  # subset, not 3
    assert scores.detected == 1


def _ranked_bundle(bug, findings, *, repository_loc=1000):
    return RankedPredictionBundle(
        protocol="repository-static-v1",
        bug_key=bug.key,
        buggy_revision=bug.buggy_commit,
        findings=tuple(findings),
        repository_files=10,
        repository_loc=repository_loc,
        analyzed_files=8,
        analyzed_loc=800 if repository_loc >= 800 else repository_loc,
    )


def test_ranked_detection_scores_top_k_noise_and_coverage(bench):
    from archway_benchmarks.scoring.bugsinpy import score_ranked_detection

    bug = next(item for item in bench.load() if item.key == "demoproj:1")
    findings = (
        RankedFinding(1, "unrelated.py", 2, 2, "value-constraint"),
        RankedFinding(2, "demoproj/core.py", 11, 11, "exception-path"),
        RankedFinding(3, "another.py", 5, 5, "bottom"),
    )
    scores, outcomes = score_ranked_detection(bench, {bug.key: _ranked_bundle(bug, findings)})

    outcome = next(item for item in outcomes if item.bug_key == bug.key)
    assert outcome.first_file_hit_rank == 2
    assert outcome.first_line_hit_rank == 2
    assert outcome.false_positive_count == 2
    assert outcome.predicted_lines == 3
    assert outcome.false_positive_lines == 2
    assert outcome.reciprocal_rank == 0.5
    assert outcome.exam_score == 0.002
    assert scores.top_line_hits == {1: 0, 5: 1, 10: 1}
    assert scores.total_findings == 3
    assert scores.exact_findings == 1
    assert scores.false_positive_findings == 2
    assert scores.false_positive_lines == 2
    assert scores.precision_at[1] == 0.0
    assert scores.precision_at[5] == pytest.approx(1 / 3)
    assert scores.findings_per_kloc == 3.0
    assert scores.file_coverage == pytest.approx(0.8)
    assert scores.loc_coverage == pytest.approx(0.8)


def test_ranked_detection_charges_broad_spans_as_false_positive_lines(bench):
    from archway_benchmarks.scoring.bugsinpy import score_ranked_detection

    bug = next(item for item in bench.load() if item.key == "demoproj:1")
    broad = (RankedFinding(1, "demoproj/core.py", 1, 100, "broad-warning"),)
    scores, outcomes = score_ranked_detection(
        bench, {bug.key: _ranked_bundle(bug, broad, repository_loc=100)}
    )
    outcome = next(item for item in outcomes if item.bug_key == bug.key)
    assert outcome.first_line_hit_rank == 1
    assert outcome.exam_score == 1.0
    assert outcome.predicted_lines == 100
    assert outcome.exact_predicted_lines == 1
    assert outcome.false_positive_lines == 99
    assert scores.precision_at[1] == pytest.approx(0.01)


def test_ranked_detection_rejects_fixed_or_wrong_revision(bench):
    from archway_benchmarks.scoring.bugsinpy import score_ranked_detection

    bug = next(item for item in bench.load() if item.key == "demoproj:1")
    bundle = RankedPredictionBundle(
        protocol="repository-static-v1",
        bug_key=bug.key,
        buggy_revision=bug.fixed_commit,
        findings=(),
        repository_files=1,
        repository_loc=10,
        analyzed_files=1,
        analyzed_loc=10,
    )
    with pytest.raises(ValueError, match="revision mismatch"):
        score_ranked_detection(bench, {bug.key: bundle})


# ----- repair mode -----

def test_repair_with_stub_runner(bench):
    from archway_benchmarks.engines.bugsinpy import CandidateFix, StubTestRunner
    from archway_benchmarks.scoring.bugsinpy import score_repair

    fixes = {"demoproj:1": "patch", "otherproj:1": "patch"}
    runner = StubTestRunner(repaired_keys={"demoproj:1"})  # only demoproj:1 actually passes
    outcomes = {}
    for bug in bench.load():
        if bug.key in fixes:
            outcomes[bug.key] = runner.run_failing_tests(bug, CandidateFix(bug.key, fixes[bug.key]))
    scores, ordered = score_repair(bench, outcomes)
    assert scores.total_bugs == 3
    assert scores.bugs_attempted == 2
    assert scores.repaired == 1
    assert scores.repaired_by_project == {"demoproj": 1}


def test_repair_runner_never_false_passes_on_error(bench):
    # The framework runner must yield a non-passing outcome on any setup failure.
    from archway_benchmarks.engines.bugsinpy import BugsInPyTestRunner, CandidateFix

    runner = BugsInPyTestRunner(corpus_root=Path("/nonexistent"),
                                framework_bin=Path("/nonexistent/bin"))
    bug = next(b for b in bench.load() if b.key == "demoproj:1")
    out = runner.run_failing_tests(bug, CandidateFix("demoproj:1", "bad patch"))
    assert out.passed is False
    assert "error" in (out.detail or "")


# ----- store + report round-trip -----

def test_store_and_report_roundtrip(bench, tmp_path):
    from archway_benchmarks import bugsinpy_report
    from archway_benchmarks.engines.bugsinpy import CandidateFix, StubTestRunner
    from archway_benchmarks.scoring.bugsinpy import score_detection, score_repair
    from archway_benchmarks.store import (connect, create_run, get_bugsinpy_scores,
                                          list_bugsinpy_detection,
                                          record_bugsinpy_detection,
                                          record_bugsinpy_repair,
                                          record_bugsinpy_scores)

    db = tmp_path / "runs.db"
    flagged = {"demoproj:1": [BugLocation(file="demoproj/core.py", start=11, end=11,
                                          lines=frozenset({11}))]}
    det_scores, det_outcomes = score_detection(bench, flagged)

    with connect(db) as conn:
        run_id = create_run(conn, benchmark="bugsinpy", engine="bugsinpy-detection",
                            stub_accuracy=None, seed=None, notes="fixture",
                            metadata={"mode": "detection", "engine_sha": "deadbeefcafe",
                                      "corpus_commit": "feedface0000", "subset": "all"})
        record_bugsinpy_detection(conn, run_id, det_outcomes)
        record_bugsinpy_scores(conn, run_id, mode="detection", scope="all", scores=det_scores)

    with connect(db) as conn:
        scores = get_bugsinpy_scores(conn, run_id)
        assert scores[("detection", "all")]["hit"] == 1
        assert scores[("detection", "all")]["total_bugs"] == 3
        rows = list_bugsinpy_detection(conn, run_id)
        assert len(rows) == 3

    # provenance shows up in the rendered report
    report = bugsinpy_report.render_run_report(db, run_id)
    assert "deadbeefcafe" in report
    assert "feedface0000" in report
    assert "Detection" in report

    progress = bugsinpy_report.render_progress(db)
    assert "demoproj" not in progress or "BugsInPy" in progress  # progress renders
    assert "deadbeefcafe"[:12] in progress
