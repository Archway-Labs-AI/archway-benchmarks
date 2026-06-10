"""BugsInPy scoring — both modes, parallel to `scoring/typeevalpy.py`.

Two first-class scorers, even though we run neither here:

  - `score_detection`: given a tool's flagged locations, join them against the
    patch-derived ground-truth regions (the bug location). Mirrors TypeEvalPy's
    structure — a per-item match predicate (`detection_match`, the analog of
    `check_match`) and an `_aggregate`-style roll-up into `DetectionScores`.
  - `score_repair`: given the per-bug `TestOutcome`s produced by the repair
    runner (the engine seam), aggregate the test-suite-passes metric into
    `RepairScores`. The scorer SCORES outcomes; the runner RUNS the tests —
    the same separation TypeEvalPy keeps between scorer and engine.

Both accept a `subset` of bug keys so a run can report 'subset AND full'.
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Iterable

from archway_benchmarks.bugsinpy_types import (
    BugLocation,
    DetectionOutcome,
    DetectionScores,
    RepairScores,
    TestOutcome,
)

if TYPE_CHECKING:
    from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark


# ----- detection mode -----

def detection_match(
    flagged: Iterable[BugLocation],
    ground_truth: Iterable[BugLocation],
    *,
    line_tolerance: int = 0,
) -> tuple[bool, bool, tuple[BugLocation, ...]]:
    """The detection join predicate — analog of TypeEvalPy's `check_match`.

    Returns `(line_level_hit, file_level_hit, matched_gt_regions)`:
      - file_level_hit: a flag landed in a file the patch touched.
      - line_level_hit: a flag's line set intersects a GT region's lines
        (optionally widened by `line_tolerance` lines on each side).
    """
    gt = tuple(ground_truth)
    gt_files = {g.file for g in gt}
    flagged = tuple(flagged)
    file_hit = any(f.file in gt_files for f in flagged)

    matched: list[BugLocation] = []
    for g in gt:
        widened = set(g.lines)
        if line_tolerance:
            for ln in list(g.lines):
                widened.update(range(ln - line_tolerance, ln + line_tolerance + 1))
            widened.update(range(g.start - line_tolerance, g.end + line_tolerance + 1))
        for f in flagged:
            if f.file != g.file:
                continue
            f_lines = set(f.lines) or set(range(f.start, f.end + 1))
            if f_lines & widened:
                matched.append(g)
                break
    return (bool(matched), file_hit, tuple(matched))


def score_detection(
    benchmark: "BugsInPyBenchmark",
    flagged: dict[str, list[BugLocation]],
    *,
    subset: set[str] | None = None,
    line_tolerance: int = 0,
) -> tuple[DetectionScores, list[DetectionOutcome]]:
    """Aggregate detection scoring. `flagged` maps `bug_key -> tool locations`.

    When `subset` is given, only those bug keys are scored (the declared-subset
    metric); bugs outside the subset are excluded from the denominator.
    """
    bugs = benchmark.load()
    if subset is not None:
        bugs = [b for b in bugs if b.key in subset]

    outcomes: list[DetectionOutcome] = []
    detected = file_level = attempted = 0
    detected_by_project: dict[str, int] = defaultdict(int)
    total_by_project: dict[str, int] = defaultdict(int)

    for bug in bugs:
        total_by_project[bug.project] += 1
        tool_locs = flagged.get(bug.key, [])
        if tool_locs:
            attempted += 1
        line_hit, file_hit, matched = detection_match(
            tool_locs, bug.bug_locations, line_tolerance=line_tolerance
        )
        if line_hit:
            detected += 1
            detected_by_project[bug.project] += 1
            kind = "DETECTED"
        elif file_hit:
            kind = "WRONG_FILE"
        else:
            kind = "MISSED"
        if file_hit:
            file_level += 1
        outcomes.append(DetectionOutcome(
            bug_key=bug.key, project=bug.project, kind=kind,
            matched_locations=matched, flagged_count=len(tool_locs),
        ))

    scores = DetectionScores(
        total_bugs=len(bugs),
        bugs_attempted=attempted,
        detected=detected,
        file_level_detected=file_level,
        detected_by_project=dict(detected_by_project),
        total_by_project=dict(total_by_project),
    )
    return scores, outcomes


# ----- repair mode -----

def score_repair(
    benchmark: "BugsInPyBenchmark",
    outcomes: dict[str, TestOutcome],
    *,
    subset: set[str] | None = None,
) -> tuple[RepairScores, list[TestOutcome]]:
    """Aggregate repair scoring from per-bug `TestOutcome`s (test-suite-passes).

    `outcomes` maps `bug_key -> TestOutcome` (produced by the repair runner).
    A bug counts as repaired iff its previously-failing tests all pass.
    """
    bugs = benchmark.load()
    if subset is not None:
        bugs = [b for b in bugs if b.key in subset]

    repaired = attempted = 0
    repaired_by_project: dict[str, int] = defaultdict(int)
    total_by_project: dict[str, int] = defaultdict(int)
    ordered: list[TestOutcome] = []

    for bug in bugs:
        total_by_project[bug.project] += 1
        out = outcomes.get(bug.key)
        if out is None:
            continue
        attempted += 1
        ordered.append(out)
        if out.passed:
            repaired += 1
            repaired_by_project[bug.project] += 1

    scores = RepairScores(
        total_bugs=len(bugs),
        bugs_attempted=attempted,
        repaired=repaired,
        repaired_by_project=dict(repaired_by_project),
        total_by_project=dict(total_by_project),
    )
    return scores, ordered
