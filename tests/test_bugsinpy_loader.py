"""BugsInPy loader + manifest tests — exercised against the fixture corpus
(tests/fixtures/bugsinpy), so no 501-bug download is needed."""
from __future__ import annotations

from pathlib import Path

import pytest

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark, _parse_patch

FIXTURE = Path(__file__).parent / "fixtures" / "bugsinpy"


@pytest.fixture
def bench() -> BugsInPyBenchmark:
    return BugsInPyBenchmark(corpus_root=FIXTURE)


def test_loads_all_fixture_bugs(bench):
    bugs = bench.load()
    keys = sorted(b.key for b in bugs)
    assert keys == ["demoproj:1", "demoproj:2", "otherproj:1"]


def test_bug_metadata_parsed(bench):
    bug = next(b for b in bench.load() if b.key == "demoproj:1")
    assert bug.buggy_commit == "aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111"
    assert bug.fixed_commit == "bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222"
    assert bug.python_version == "3.8.0"
    assert bug.github_url == "https://github.com/demo/demoproj"
    # test_list is `;`-separated -> two failing tests
    assert bug.failing_tests == (
        "tests/test_core.py::test_add",
        "tests/test_core.py::test_sub",
    )


def test_detection_gt_from_removed_line(bench):
    # demoproj:1 removes buggy line 11 (`return a + b + 1`) — that's the GT location.
    bug = next(b for b in bench.load() if b.key == "demoproj:1")
    assert bug.files_touched == ("demoproj/core.py",)
    assert bug.n_files_touched == 1
    (loc,) = bug.bug_locations
    assert loc.file == "demoproj/core.py"
    assert 11 in loc.lines


def test_detection_gt_pure_insertion_brackets(bench):
    # demoproj:2 inserts `return lo` between buggy lines 40 (`if x < lo:`) and
    # 41 (`return x`). A pure insertion has no removed line, so the GT brackets
    # the gap the fix fills — both lines, not a single hunk-start anchor.
    bug = next(b for b in bench.load() if b.key == "demoproj:2")
    (loc,) = bug.bug_locations
    assert loc.file == "demoproj/util.py"
    assert loc.lines == frozenset({40, 41})


def test_multi_file_patch(bench):
    bug = next(b for b in bench.load() if b.key == "otherproj:1")
    assert bug.n_files_touched == 2
    assert set(bug.files_touched) == {"otherproj/a.py", "otherproj/b.py"}
    assert bug.lines_changed == 2  # one removed line per file


def test_subset_by_project(bench):
    subset = bench.subset(projects=["demoproj"])
    assert {b.key for b in subset} == {"demoproj:1", "demoproj:2"}


def test_subset_by_key(bench):
    subset = bench.subset(bug_keys=["demoproj:1", "otherproj:1"])
    assert {b.key for b in subset} == {"demoproj:1", "otherproj:1"}


def test_ground_truth_detection_shape(bench):
    gt = bench.ground_truth_detection()
    assert set(gt) == {"demoproj:1", "demoproj:2", "otherproj:1"}
    assert all(isinstance(v, tuple) for v in gt.values())


def test_missing_corpus_raises_with_hint():
    with pytest.raises(FileNotFoundError, match="submodule"):
        BugsInPyBenchmark(corpus_root=Path("/nonexistent/bugsinpy"))


def test_parse_patch_directly():
    patch = (
        "diff --git a/m.py b/m.py\n"
        "--- a/m.py\n+++ b/m.py\n"
        "@@ -5,3 +5,3 @@\n x = 1\n-    bad = 2\n+    good = 2\n"
    )
    (loc,) = _parse_patch(patch)
    assert loc.file == "m.py"
    assert loc.lines == frozenset({6})  # the removed line


def test_parse_patch_pure_insertion_brackets():
    # No removed line: GT = the buggy lines bracketing the insertion point
    # (the existing line before and after), not just the hunk-start anchor.
    patch = (
        "diff --git a/u.py b/u.py\n"
        "--- a/u.py\n+++ b/u.py\n"
        "@@ -40,2 +40,3 @@\n     if x < lo:\n+        return lo\n     return x\n"
    )
    (loc,) = _parse_patch(patch)
    assert loc.file == "u.py"
    assert loc.lines == frozenset({40, 41})


def test_manifest_metadata_only(bench):
    from archway_benchmarks import bugsinpy_manifest

    manifest = bugsinpy_manifest.generate(bench)
    assert manifest.total_bugs == 3
    s = manifest.summary()
    assert s["n_projects"] == 2
    assert s["single_file_bugs"] == 2  # demoproj:1, demoproj:2
    assert s["multi_file_bugs"] == 1  # otherproj:1
    # the manifest exposes fix-shape but makes NO tractability judgment
    rec = next(b for b in manifest.bugs if b.key == "otherproj:1")
    assert rec.single_file is False
    assert not hasattr(rec, "tractable")
