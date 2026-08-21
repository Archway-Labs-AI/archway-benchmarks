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
    RankedDetectionOutcome,
    RankedDetectionScores,
    TestOutcome,
)
from archway_benchmarks.bugsinpy_protocol import RankedFinding, RankedPredictionBundle

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


def _finding_match(
    finding: RankedFinding,
    ground_truth: Iterable[BugLocation],
) -> tuple[bool, bool, int]:
    file_hit = False
    line_hit = False
    exact_lines: set[int] = set()
    for location in ground_truth:
        if finding.file != location.file:
            continue
        file_hit = True
        gt_lines = location.lines or frozenset(range(location.start, location.end + 1))
        if finding.lines() & gt_lines:
            line_hit = True
            exact_lines.update(finding.lines() & gt_lines)
    return file_hit, line_hit, len(exact_lines)


def score_ranked_detection(
    benchmark: "BugsInPyBenchmark",
    predictions: dict[str, RankedPredictionBundle],
    *,
    subset: set[str] | None = None,
    cutoffs: tuple[int, ...] = (1, 5, 10),
) -> tuple[RankedDetectionScores, list[RankedDetectionOutcome]]:
    """Score sealed, repository-wide predictions without exposing GT to execution.

    ``exam_score`` is the cumulative predicted-line span through the first exact
    finding divided by repository LOC, capped at one; a miss receives one. It
    therefore charges broad findings against the repository inspection budget.
    ``precision_at`` is micro line precision across the first K findings per bug.
    """
    if not cutoffs or any(value < 1 for value in cutoffs):
        raise ValueError("rank cutoffs must be positive")
    cutoffs = tuple(sorted(set(cutoffs)))
    bugs = benchmark.load()
    if subset is not None:
        bugs = [bug for bug in bugs if bug.key in subset]

    outcomes: list[RankedDetectionOutcome] = []
    top_file_hits = {cutoff: 0 for cutoff in cutoffs}
    top_line_hits = {cutoff: 0 for cutoff in cutoffs}
    inspected = {cutoff: 0 for cutoff in cutoffs}
    correct = {cutoff: 0 for cutoff in cutoffs}
    project_hits: dict[str, int] = defaultdict(int)
    project_totals: dict[str, int] = defaultdict(int)

    for bug in bugs:
        project_totals[bug.project] += 1
        bundle = predictions.get(bug.key)
        if bundle is None:
            findings: tuple[RankedFinding, ...] = ()
            repository_files = repository_loc = analyzed_files = analyzed_loc = 0
        else:
            if bundle.bug_key != bug.key:
                raise ValueError(f"prediction key mismatch: {bug.key} != {bundle.bug_key}")
            if bundle.buggy_revision != bug.buggy_commit:
                raise ValueError(f"prediction revision mismatch for {bug.key}")
            findings = bundle.findings
            repository_files = bundle.repository_files
            repository_loc = bundle.repository_loc
            analyzed_files = bundle.analyzed_files
            analyzed_loc = bundle.analyzed_loc

        matches = [_finding_match(finding, bug.bug_locations) for finding in findings]
        file_ranks = [item.rank for item, match in zip(findings, matches, strict=True) if match[0]]
        line_ranks = [item.rank for item, match in zip(findings, matches, strict=True) if match[1]]
        first_file = min(file_ranks, default=None)
        first_line = min(line_ranks, default=None)
        exact_count = sum(match[1] for match in matches)
        false_positives = len(findings) - exact_count
        predicted_lines = sum(len(item.lines()) for item in findings)
        exact_predicted_lines = sum(match[2] for match in matches)
        reciprocal_rank = 0.0 if first_line is None else 1.0 / first_line
        inspected_lines = (
            0
            if first_line is None
            else sum(len(item.lines()) for item in findings[:first_line])
        )
        exam_score = (
            1.0
            if first_line is None or repository_loc <= 0
            else min(1.0, inspected_lines / repository_loc)
        )
        if first_line is not None:
            project_hits[bug.project] += 1
        for cutoff in cutoffs:
            top_file_hits[cutoff] += first_file is not None and first_file <= cutoff
            top_line_hits[cutoff] += first_line is not None and first_line <= cutoff
            prefix = matches[:cutoff]
            inspected[cutoff] += sum(len(item.lines()) for item in findings[:cutoff])
            correct[cutoff] += sum(match[2] for match in prefix)
        outcomes.append(RankedDetectionOutcome(
            bug_key=bug.key,
            project=bug.project,
            finding_count=len(findings),
            exact_finding_count=exact_count,
            false_positive_count=false_positives,
            predicted_lines=predicted_lines,
            exact_predicted_lines=exact_predicted_lines,
            false_positive_lines=predicted_lines - exact_predicted_lines,
            first_file_hit_rank=first_file,
            first_line_hit_rank=first_line,
            reciprocal_rank=reciprocal_rank,
            exam_score=exam_score,
            repository_files=repository_files,
            repository_loc=repository_loc,
            analyzed_files=analyzed_files,
            analyzed_loc=analyzed_loc,
        ))

    total_findings = sum(item.finding_count for item in outcomes)
    exact_findings = sum(item.exact_finding_count for item in outcomes)
    repository_loc = sum(item.repository_loc for item in outcomes)
    scores = RankedDetectionScores(
        total_bugs=len(bugs),
        top_file_hits=top_file_hits,
        top_line_hits=top_line_hits,
        mean_reciprocal_rank=(
            sum(item.reciprocal_rank for item in outcomes) / len(outcomes) if outcomes else 0.0
        ),
        mean_exam_score=(
            sum(item.exam_score for item in outcomes) / len(outcomes) if outcomes else 0.0
        ),
        total_findings=total_findings,
        exact_findings=exact_findings,
        false_positive_findings=total_findings - exact_findings,
        predicted_lines=sum(item.predicted_lines for item in outcomes),
        exact_predicted_lines=sum(item.exact_predicted_lines for item in outcomes),
        false_positive_lines=sum(item.false_positive_lines for item in outcomes),
        precision_at={
            cutoff: correct[cutoff] / inspected[cutoff] if inspected[cutoff] else 0.0
            for cutoff in cutoffs
        },
        findings_per_kloc=(total_findings * 1000 / repository_loc if repository_loc else 0.0),
        repository_files=sum(item.repository_files for item in outcomes),
        repository_loc=repository_loc,
        analyzed_files=sum(item.analyzed_files for item in outcomes),
        analyzed_loc=sum(item.analyzed_loc for item in outcomes),
        macro_line_hit_rate_by_project={
            project: project_hits[project] / total
            for project, total in sorted(project_totals.items())
        },
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
