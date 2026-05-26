"""Lenient (publication-era) scoring against TypeEvalPy current GT.

Uses `vendor/TypeEvalPy/src/result_analyzer/large_scale_analysis.check_match`
verbatim — that scorer has the `col_offset` and `line_number` checks
commented out (lines 46-51) and matches predictions to GT on
`file + function/parameter/variable + type` only.

Why this exists: TypeEvalPy commit `2f7c6056` (Oct 2025) added a stricter
`is_same_element` to `analysis_utils.check_match` that requires col_offset
match. Tool runners (Jedi, Scalpel, HeaderGen) do NOT emit col_offset, so
under the new strict scorer they all score 0 — but the published Jan 2024
paper_table_*.csv numbers were generated with the looser pre-Oct-2025
scorer. To get a like-for-like comparison against the published board, we
score baselines with this lenient predicate. The harness's *internal*
scoring stays strict (see `scoring/typeevalpy.py`) because Archway's
analysis layer can and must emit col_offset.

Both scorers are vendor code; this is reuse, not reimplementation.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from archway_benchmarks.types import Location, Scores

if TYPE_CHECKING:
    from archway_benchmarks.benchmarks.typeevalpy import TypeEvalPyBenchmark


# Vendor scorer bootstrap.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_VENDOR_SRC = _REPO_ROOT / "vendor" / "TypeEvalPy" / "src"
_VENDOR_RA = _VENDOR_SRC / "result_analyzer"
for p in (_VENDOR_SRC, _VENDOR_RA):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from large_scale_analysis import check_match as _lenient_check  # noqa: E402


@dataclass
class LenientSnippetScores:
    suite_path: str
    exact_count: int
    total_gt: int
    matched_locations: list[Location]


def score_snippet_lenient(
    suite_path: str,
    ground_truth: dict[Location, frozenset[str]],
    predictions: dict[Location, frozenset[str]],
    location_to_record,
) -> LenientSnippetScores:
    """Per-snippet lenient scoring. Returns exact count + which GT
    locations matched. We deliberately drop SPURIOUS/TYPE_MISS bookkeeping
    here — the lenient scorer is for the comparison number only; the
    three-bucket inspector view is owned by the strict scorer."""
    matched: list[Location] = []
    out_records = [
        location_to_record(loc, types) for loc, types in predictions.items()
    ]
    for gt_loc, gt_types in ground_truth.items():
        gt_record = location_to_record(gt_loc, gt_types)
        for out_record in out_records:
            is_exact, _is_partial = _lenient_check(expected=gt_record, out=out_record)
            if is_exact:
                matched.append(gt_loc)
                break
    return LenientSnippetScores(
        suite_path=suite_path,
        exact_count=len(matched),
        total_gt=len(ground_truth),
        matched_locations=matched,
    )


def score_predictions_lenient(
    benchmark: "TypeEvalPyBenchmark",
    predictions: dict[Location, frozenset[str]],
    *,
    covered_snippet_paths: set[str] | None = None,
) -> Scores:
    """Aggregate lenient scoring into a `Scores` row.

    Files-sound and files-complete are computed under the same predicate:
    sound iff every GT in the snippet matched leniently, complete iff every
    prediction in the snippet matched some GT leniently. Per-annotation
    precision/recall are also lenient.
    """
    snippets = benchmark.load()
    from archway_benchmarks.benchmarks.typeevalpy import _location_to_record

    file_id_to_suite = {snip.file_path: snip.suite_path for snip in snippets}
    gt_by_snippet: dict[str, dict[Location, frozenset[str]]] = defaultdict(dict)
    pred_by_snippet: dict[str, dict[Location, frozenset[str]]] = defaultdict(dict)

    for snip in snippets:
        for ann in snip.annotations:
            gt_by_snippet[snip.suite_path][ann.location] = ann.types
    for loc, types in predictions.items():
        sp = file_id_to_suite.get(loc.file)
        if sp is not None:
            pred_by_snippet[sp][loc] = types

    selected = (
        [s for s in snippets if s.suite_path in covered_snippet_paths]
        if covered_snippet_paths is not None
        else snippets
    )

    per_snippet: list[LenientSnippetScores] = []
    files_sound = 0
    files_complete = 0
    spurious_total = 0
    for snip in selected:
        s = score_snippet_lenient(
            suite_path=snip.suite_path,
            ground_truth=gt_by_snippet[snip.suite_path],
            predictions=pred_by_snippet.get(snip.suite_path, {}),
            location_to_record=_location_to_record,
        )
        per_snippet.append(s)
        if s.exact_count == s.total_gt:
            files_sound += 1
        # complete: every prediction matched some GT
        snippet_preds = pred_by_snippet.get(snip.suite_path, {})
        if snippet_preds:
            # Count predictions that found at least one GT match.
            unmatched_preds = 0
            gt_records = [_location_to_record(g, t) for g, t in gt_by_snippet[snip.suite_path].items()]
            for ploc, ptypes in snippet_preds.items():
                prec = _location_to_record(ploc, ptypes)
                if not any(_lenient_check(expected=g, out=prec)[0] for g in gt_records):
                    unmatched_preds += 1
            if unmatched_preds == 0:
                files_complete += 1
            spurious_total += unmatched_preds
        else:
            # No predictions at all: trivially complete (no false positives).
            files_complete += 1

    exact_total = sum(s.exact_count for s in per_snippet)
    total_annotations = sum(s.total_gt for s in per_snippet)

    # exact_by_kind: walk the matches.
    exact_by_kind: dict[str, int] = {"return": 0, "parameter": 0, "variable": 0}
    exact_by_category: dict[str, int] = defaultdict(int)
    for s in per_snippet:
        for loc in s.matched_locations:
            exact_by_kind[loc.kind] += 1
            cat = s.suite_path.split("/", 1)[0]
            exact_by_category[cat] += 1

    pred_total = sum(
        len(pred_by_snippet.get(s.suite_path, {})) for s in per_snippet
    )
    annotation_precision = (
        exact_total / pred_total if pred_total else 0.0
    )
    annotation_recall = exact_total / total_annotations if total_annotations else 0.0

    return Scores(
        total_snippets=len(per_snippet),
        total_annotations=total_annotations,
        files_sound=files_sound,
        files_complete=files_complete,
        exact_total=exact_total,
        exact_by_kind=dict(exact_by_kind),
        exact_by_category=dict(exact_by_category),
        annotation_precision=annotation_precision,
        annotation_recall=annotation_recall,
    )
