"""DIRECTIONAL bucketer tests: patch-evidenced classes, confidence, re-computability,
and the detection × bucket join. Heuristics are diagnostic — these pin behaviour,
not ground truth."""
from __future__ import annotations

from pathlib import Path

import pytest

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark
from archway_benchmarks.bugsinpy_bucketer import (
    BUCKETER_VERSION,
    bucket_all,
    bucket_bug,
    needs_adjudication,
    summarize,
)
from archway_benchmarks.bugsinpy_types import BugRecord

FIXTURE = Path(__file__).parent / "fixtures" / "bugsinpy"


def _bug(patch: str, key: str = "p:1") -> BugRecord:
    project, _, bug_id = key.partition(":")
    return BugRecord(
        project=project, bug_id=bug_id, buggy_commit="x", fixed_commit="y",
        bug_locations=(), failing_tests=(), test_files=(), patch=patch,
        python_version=None, github_url=None, files_touched=(),
        n_files_touched=0, lines_changed=0,
    )


def _diff(*added_removed: str) -> str:
    """Build a minimal diff body from +/- prefixed lines."""
    head = "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1,3 +1,4 @@\n"
    return head + "\n".join(added_removed) + "\n"


@pytest.mark.parametrize("lines,bucket,confidence", [
    (["+    try:", "+        x()", "+    except KeyError:", "+        pass"], "exception_handling", "high"),
    (["+    if x is None:", "+        return"], "none_or_null", "high"),
    (["+    if isinstance(x, int):", "+        pass"], "type_check", "high"),
    (["+    if flag:", "+        do()"], "missing_branch", "high"),
    (["+        return lo"], "missing_branch", "low"),  # guard inserted, nothing removed
    (["-    df.sort(columns=c)", "+    df.sort_values(by=c)"], "api_misuse_lib", "low"),
    (["-    return a + b + 1", "+    return a + b"], "other", "low"),  # changed return -> not a branch
])
def test_patch_evidence_classes(lines, bucket, confidence):
    r = bucket_bug(_bug(_diff(*lines)))
    assert r.bucket == bucket, f"{lines} -> {r.bucket} ({r.evidence})"
    assert r.confidence == confidence


def test_api_misuse_always_low_and_adjudicable():
    r = bucket_bug(_bug(_diff("-    obj.foo(a)", "+    obj.bar(a)")))
    assert r.bucket == "api_misuse_lib"
    assert r.confidence == "low"
    assert r.needs_adjudication is True


def test_version_is_tagged():
    r = bucket_bug(_bug(_diff("+    if x is None: pass")), version="vtest")
    assert r.bucketer_version == "vtest"


def test_fixture_bugs_bucket_without_error():
    bench = BugsInPyBenchmark(corpus_root=FIXTURE)
    results = bucket_all(bench)
    assert len(results) == 3
    s = summarize(results)
    assert s["bucketer_version"] == BUCKETER_VERSION
    assert s["total"] == 3
    # demoproj:2 inserts a guard return -> missing_branch; demoproj:1/otherproj:1 are
    # changed-return arithmetic -> other. All directional.
    by_key = {r.bug_key: r for r in results}
    assert by_key["demoproj:2"].bucket == "missing_branch"
    assert by_key["demoproj:1"].bucket == "other"


def test_needs_adjudication_queue():
    results = [
        bucket_bug(_bug(_diff("+    if x is None: pass"), "a:1")),       # high -> not queued
        bucket_bug(_bug(_diff("-    o.f(x)", "+    o.g(x)"), "a:2")),     # api_misuse_lib -> queued
        bucket_bug(_bug(_diff("+    return a"), "a:3")),                  # missing_branch low -> queued
    ]
    queue = needs_adjudication(results)
    assert {r.bug_key for r in queue} == {"a:2", "a:3"}


# ----- re-computability + detection × bucket join -----

def test_buckets_recomputable_without_rerun(tmp_path):
    """Re-running the bucketer (new version) re-buckets stored detection results
    WITHOUT touching the detection run rows."""
    from archway_benchmarks.bugsinpy_types import BugLocation
    from archway_benchmarks.scoring.bugsinpy import score_detection
    from archway_benchmarks.store import (connect, create_run, get_bugsinpy_buckets,
                                          list_bugsinpy_bucket_versions,
                                          list_bugsinpy_detection,
                                          record_bugsinpy_buckets,
                                          record_bugsinpy_detection,
                                          record_bugsinpy_scores)

    bench = BugsInPyBenchmark(corpus_root=FIXTURE)
    db = tmp_path / "runs.db"

    # 1. a detection run (the benchmark "result")
    flagged = {"demoproj:1": [BugLocation(file="demoproj/core.py", start=11, end=11,
                                          lines=frozenset({11}))]}
    scores, outcomes = score_detection(bench, flagged)
    with connect(db) as conn:
        run_id = create_run(conn, benchmark="bugsinpy", engine="bugsinpy-detection",
                            stub_accuracy=None, seed=None,
                            metadata={"mode": "detection", "engine_sha": "e1", "subset": "all"})
        record_bugsinpy_detection(conn, run_id, outcomes)
        record_bugsinpy_scores(conn, run_id, mode="detection", scope="all", scores=scores)
        det_before = list_bugsinpy_detection(conn, run_id)

    # 2. bucket at v1, then RE-bucket at v2 — detection rows must be untouched
    with connect(db) as conn:
        record_bugsinpy_buckets(conn, bucket_all(bench, version="v1"))
    with connect(db) as conn:
        record_bugsinpy_buckets(conn, bucket_all(bench, version="v2"))
        assert set(list_bugsinpy_bucket_versions(conn)) == {"v1", "v2"}
        assert len(get_bugsinpy_buckets(conn, "v1")) == 3
        det_after = list_bugsinpy_detection(conn, run_id)
    assert det_before == det_after  # the benchmark result was NOT re-run

    # 3. detection × bucket report renders with the DIRECTIONAL label
    from archway_benchmarks import bugsinpy_report
    report = bugsinpy_report.render_detection_by_bucket(db, run_id, version="v1")
    assert "DIRECTIONAL" in report
    assert "Needs adjudication" in report
    assert "v1" in report
