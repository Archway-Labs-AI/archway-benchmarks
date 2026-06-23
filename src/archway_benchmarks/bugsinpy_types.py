"""Core types for the BugsInPy benchmark — parallel to `types.py` (TypeEvalPy).

BugsInPy is a different *shape* of benchmark from TypeEvalPy: the spine is not
`Location -> types` but `(project, bug) -> {buggy region, failing tests}`. So we
mirror TypeEvalPy's structure with a parallel, dependency-free type module
rather than forcing bugs through the type-annotation `Location`/`Annotation`
pair. Two scoring modes are first-class from the start (see `BugMode`):

  - DETECTION: did a tool flag the bug's location? (scored vs the patch's
    touched lines — Track 1, deterministic analysis)
  - REPAIR:    did a candidate fix make the failing tests pass? (scored vs the
    test suite — Track 2, the later agent experiment)

Keep this module dependency-free, exactly like `types.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BugMode = Literal["detection", "repair"]
FindingSignalKind = Literal["bottom"]
SourcePositionBasis = Literal[
    "direct-node",
    "defining-expr",
    "enclosing-function",
    "rowless",
    "unknown",
]


@dataclass(frozen=True)
class BugLocation:
    """A contiguous touched region in the BUGGY version of a file.

    Derived from a `bug_patch.txt` hunk's old-side range (`@@ -start,len ... @@`).
    `lines` is the concrete set of buggy-side line numbers the patch changed —
    the detection oracle joins a tool's flagged lines against this.
    """

    file: str  # repo-relative path
    start: int  # first buggy-side line touched (1-indexed)
    end: int  # last buggy-side line touched (inclusive)
    lines: frozenset[int] = field(default_factory=frozenset)  # exact changed lines


@dataclass(frozen=True)
class FindingCandidate:
    """Benchmark-side readout record for analysis facts that may localize a bug.

    The initial BugsInPy consumer builds these records from existing bottom facts
    only. Future consumers can add other signal kinds without changing the
    detection scorer's strict flag shape.
    """

    bug_key: str
    file: str | None
    line: int | None
    span: tuple[int, int] | None
    signal_kind: FindingSignalKind
    strict_score_eligible: bool
    source_position_basis: SourcePositionBasis
    provenance_classification: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "bug_key": self.bug_key,
            "file": self.file,
            "line": self.line,
            "span": (
                {"start": self.span[0], "end": self.span[1]}
                if self.span is not None
                else None
            ),
            "signal_kind": self.signal_kind,
            "strict_score_eligible": self.strict_score_eligible,
            "source_position_basis": self.source_position_basis,
            "provenance_classification": self.provenance_classification,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class BugRecord:
    """One BugsInPy bug: the buggy/fixed refs, the patch, the failing tests, and
    the fix metadata downstream work can filter on WITHOUT this module classifying.

    `files_touched` / `lines_changed` are exposed precisely so a LATER
    pre-classification pass can subset by bug shape; nothing here decides
    tractability or runs anything.
    """

    project: str
    bug_id: str
    buggy_commit: str
    fixed_commit: str
    bug_locations: tuple[BugLocation, ...]  # detection ground truth (patch-derived)
    failing_tests: tuple[str, ...]  # test ids that fail on buggy, pass on fixed
    test_files: tuple[str, ...]
    patch: str  # raw bug_patch.txt
    python_version: str | None
    github_url: str | None
    # ---- fix-shape metadata (for later subsetting; not interpreted here) ----
    files_touched: tuple[str, ...]
    n_files_touched: int
    lines_changed: int  # total buggy-side lines the patch touches

    @property
    def key(self) -> str:
        """Stable `project:bug_id` identity used as the join key everywhere."""
        return f"{self.project}:{self.bug_id}"


# ----- detection-mode scoring -----

DetectionOutcomeKind = Literal["DETECTED", "MISSED", "WRONG_FILE"]


@dataclass(frozen=True)
class DetectionOutcome:
    """Per-bug detection result — persisted in the run store (parallel to
    TypeEvalPy's `AnnotationOutcome`)."""

    bug_key: str
    project: str
    kind: DetectionOutcomeKind
    matched_locations: tuple[BugLocation, ...]  # GT regions a flag landed in
    flagged_count: int  # how many locations the tool flagged for this bug


@dataclass(frozen=True)
class DetectionScores:
    """Aggregate detection metrics — parallel to TypeEvalPy `Scores`."""

    total_bugs: int
    bugs_attempted: int  # bugs the tool flagged anything for
    detected: int  # bugs whose flag overlapped a GT region (line-level)
    file_level_detected: int  # bugs flagged in the right FILE (looser predicate)
    detected_by_project: dict[str, int] = field(default_factory=dict)
    total_by_project: dict[str, int] = field(default_factory=dict)

    @property
    def detection_rate(self) -> float:
        return self.detected / self.total_bugs if self.total_bugs else 0.0


# ----- repair-mode scoring -----


@dataclass(frozen=True)
class TestOutcome:
    """The result of running a bug's failing tests against a candidate fix.

    Produced by the repair runner (the engine seam, `engines/bugsinpy.py`),
    consumed by `scoring.bugsinpy.score_repair`. `passed` is the BugsInPy
    plausibility signal: every previously-failing test now passes.
    """

    bug_key: str
    project: str
    passed: bool  # all failing tests pass on the candidate fix
    n_tests: int
    n_passed: int
    n_failed: int
    detail: str | None = None  # runner stdout/stderr tail, or skip reason


@dataclass(frozen=True)
class RepairScores:
    """Aggregate repair metrics — parallel to TypeEvalPy `Scores`."""

    total_bugs: int
    bugs_attempted: int  # bugs a candidate fix was supplied for
    repaired: int  # bugs whose failing tests all pass on the fix
    repaired_by_project: dict[str, int] = field(default_factory=dict)
    total_by_project: dict[str, int] = field(default_factory=dict)

    @property
    def repair_rate(self) -> float:
        return self.repaired / self.total_bugs if self.total_bugs else 0.0
