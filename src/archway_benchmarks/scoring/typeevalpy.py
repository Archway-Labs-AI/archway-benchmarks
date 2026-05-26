"""Three-bucket scoring on top of TypeEvalPy's `result_analyzer` primitives.

We re-use the vendored primitives — do NOT redefine the metrics:
  - `is_same_element` — the location join key
    (vendor/TypeEvalPy/src/result_analyzer/analysis_utils.py:173-183)
  - `format_type` / `transform_type_string` — normalization
    (vendor/TypeEvalPy/src/result_analyzer/analysis_utils.py:107-170)
  - `check_match` — exact-match predicate (combines the two above)
    (vendor/TypeEvalPy/src/result_analyzer/analysis_utils.py:186-257)

`equal_sound` / `equal_complete` in the vendor module operate on file paths;
we apply the same predicate in memory on the same `check_match` primitive,
per snippet, to compute per-file binary sound/complete (TypeEvalPy's canonical
metric). This is reuse, not reimplementation — the metric definition still
lives upstream and any future change in their `check_match` is inherited.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from archway_benchmarks.outcome import Outcome
from archway_benchmarks.rule_buckets import classify, empty_bucket_kind_table
from archway_benchmarks.types import Location, Scores

if TYPE_CHECKING:
    from archway_benchmarks.benchmarks.typeevalpy import TypeEvalPyBenchmark


# ----- vendor scorer bootstrap -----

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VENDOR_SRC = _REPO_ROOT / "vendor" / "TypeEvalPy" / "src"
if str(_VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(_VENDOR_SRC))

from result_analyzer.analysis_utils import (  # noqa: E402  -- after sys.path patch
    check_match,
    is_same_element,
)


@dataclass(frozen=True)
class AnnotationOutcome:
    """Per-annotation outcome, persisted in the run store."""

    location: Location
    outcome: Outcome
    expected_types: frozenset[str]
    predicted_types: frozenset[str] | None  # None for LOCATION_MISS
    category: str  # the python_features subdir (1 of 18)


@dataclass
class SnippetScores:
    """Per-snippet roll-up used to compute per-file sound/complete."""

    suite_path: str
    outcomes: list[AnnotationOutcome] = field(default_factory=list)
    spurious_predictions: list[tuple[Location, frozenset[str]]] = field(default_factory=list)

    @property
    def is_sound(self) -> bool:
        """True iff every GT annotation in this snippet is EXACT.

        Mirrors `equal_sound` (analysis_utils.py:548-572): zero false
        negatives — i.e. all GT facts are caught with correct type sets.
        """
        return all(o.outcome == Outcome.EXACT for o in self.outcomes)

    @property
    def is_complete(self) -> bool:
        """True iff every prediction in this snippet is EXACT (no SPURIOUS).

        Mirrors `equal_complete` (analysis_utils.py:575-600): zero false
        positives — no prediction is unmatched in GT.
        """
        return (not self.spurious_predictions) and all(
            o.outcome != Outcome.TYPE_MISS for o in self.outcomes
        )


def score_snippet(
    suite_path: str,
    ground_truth: dict[Location, frozenset[str]],
    predictions: dict[Location, frozenset[str]],
    location_to_record,
) -> SnippetScores:
    """Score one snippet, returning per-annotation outcomes + spurious list.

    `location_to_record` is the benchmark's `Location -> TypeEvalPy record`
    projector — we use it so `check_match` sees records in the schema it was
    written for, instead of our internal types.
    """
    category = suite_path.split("/", 1)[0]
    matched_pred_locations: set[Location] = set()
    outcomes: list[AnnotationOutcome] = []

    for gt_loc, gt_types in ground_truth.items():
        gt_record = location_to_record(gt_loc, gt_types)

        # Find prediction(s) whose join key matches GT location.
        pred_loc, pred_types = _find_predicted(predictions, gt_loc, location_to_record, gt_record)

        if pred_loc is None:
            outcomes.append(
                AnnotationOutcome(
                    location=gt_loc,
                    outcome=Outcome.LOCATION_MISS,
                    expected_types=gt_types,
                    predicted_types=None,
                    category=category,
                )
            )
            continue

        matched_pred_locations.add(pred_loc)
        pred_record = location_to_record(pred_loc, pred_types)

        if check_match(expected=gt_record, out=pred_record):
            outcome = Outcome.EXACT
        else:
            outcome = Outcome.TYPE_MISS

        outcomes.append(
            AnnotationOutcome(
                location=gt_loc,
                outcome=outcome,
                expected_types=gt_types,
                predicted_types=pred_types,
                category=category,
            )
        )

    spurious = [
        (loc, types)
        for loc, types in predictions.items()
        if loc not in matched_pred_locations
    ]

    return SnippetScores(suite_path=suite_path, outcomes=outcomes, spurious_predictions=spurious)


def _find_predicted(
    predictions: dict[Location, frozenset[str]],
    gt_loc: Location,
    location_to_record,
    gt_record: dict,
) -> tuple[Location | None, frozenset[str] | None]:
    """Find a predicted entry whose TypeEvalPy join key matches GT's.

    We try a direct Location lookup first (fast path); fall back to scanning
    via `is_same_element` to be tolerant of e.g. an `Optional[col]` mismatch
    where one side has `None` and the other 0.
    """
    if gt_loc in predictions:
        return gt_loc, predictions[gt_loc]

    for loc, types in predictions.items():
        candidate_record = location_to_record(loc, types)
        if is_same_element(gt_record, candidate_record):
            return loc, types
    return None, None


def score_predictions(
    benchmark: "TypeEvalPyBenchmark",
    predictions: dict[Location, frozenset[str]],
    *,
    covered_snippet_paths: set[str] | None = None,
) -> Scores:
    """Aggregate per-snippet scoring into the harness-wide `Scores`.

    When `covered_snippet_paths` is given, snippets outside the set are
    excluded from the aggregate (the "covered subset" metric).
    """
    snippets = benchmark.load()
    from archway_benchmarks.benchmarks.typeevalpy import _location_to_record

    # Group GT and predictions by snippet path for per-file scoring.
    gt_by_snippet: dict[str, dict[Location, frozenset[str]]] = defaultdict(dict)
    pred_by_snippet: dict[str, dict[Location, frozenset[str]]] = defaultdict(dict)

    snippet_paths_by_file: dict[str, str] = {}
    for snip in snippets:
        snippet_paths_by_file[snip.file_path] = snip.suite_path
        for ann in snip.annotations:
            gt_by_snippet[snip.suite_path][ann.location] = ann.types

    for loc, types in predictions.items():
        suite_path = snippet_paths_by_file.get(loc.file)
        if suite_path is None:
            # Prediction outside any known snippet — global spurious; bucket
            # it under a sentinel so it still hurts complete.
            suite_path = "__unknown__"
        pred_by_snippet[suite_path][loc] = types

    selected_snippets = (
        [s for s in snippets if s.suite_path in covered_snippet_paths]
        if covered_snippet_paths is not None
        else snippets
    )

    per_snippet: list[SnippetScores] = []
    for snip in selected_snippets:
        per_snippet.append(
            score_snippet(
                suite_path=snip.suite_path,
                ground_truth=gt_by_snippet[snip.suite_path],
                predictions=pred_by_snippet.get(snip.suite_path, {}),
                location_to_record=_location_to_record,
            )
        )

    return _aggregate(per_snippet)


def _aggregate(per_snippet: list[SnippetScores]) -> Scores:
    files_sound = sum(1 for s in per_snippet if s.is_sound)
    files_complete = sum(1 for s in per_snippet if s.is_complete)

    exact_total = 0
    type_miss_total = 0
    location_miss_total = 0
    spurious_total = 0
    exact_by_kind: dict[str, int] = {"return": 0, "parameter": 0, "variable": 0}
    exact_by_category: dict[str, int] = defaultdict(int)
    exact_by_bucket_kind = empty_bucket_kind_table()
    total_annotations = 0

    for snip in per_snippet:
        spurious_total += len(snip.spurious_predictions)
        for o in snip.outcomes:
            total_annotations += 1
            if o.outcome == Outcome.EXACT:
                exact_total += 1
                exact_by_kind[o.location.kind] += 1
                exact_by_category[o.category] += 1
                bucket = classify(o.expected_types)
                exact_by_bucket_kind[bucket][o.location.kind] += 1
            elif o.outcome == Outcome.TYPE_MISS:
                type_miss_total += 1
            elif o.outcome == Outcome.LOCATION_MISS:
                location_miss_total += 1

    emitted = exact_total + type_miss_total + spurious_total
    precision = exact_total / emitted if emitted else 0.0
    recall = exact_total / total_annotations if total_annotations else 0.0

    return Scores(
        total_snippets=len(per_snippet),
        total_annotations=total_annotations,
        files_sound=files_sound,
        files_complete=files_complete,
        exact_total=exact_total,
        exact_by_kind=dict(exact_by_kind),
        exact_by_category=dict(exact_by_category),
        exact_by_bucket_kind=exact_by_bucket_kind,
        annotation_precision=precision,
        annotation_recall=recall,
    )
